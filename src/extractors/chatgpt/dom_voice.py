"""Pass 2 — DOM scrape pras convs candidatas a voice mode.

Estrategia:
  1. detect_voice_candidates: heuristica no raw (>= threshold% msgs sem text)
  2. capture_voice_dom: pra cada candidato, abre Playwright page e extrai texto

Fase 0 (pre-requisito): rodar scripts/dev/inspect-chatgpt-voice-dom.py
pra descobrir seletores CSS corretos. Popular SELECTORS abaixo com resultado.
"""

import asyncio
import logging
from typing import Iterable

from src.extractors.chatgpt.models import VoiceCapture, VoiceMessage

logger = logging.getLogger(__name__)


# Seletores CSS descobertos via Fase 0. Lista por key = fallback chain.
# TODO(fase-0): atualizar com seletores reais apos inspect-chatgpt-voice-dom.py.
SELECTORS = {
    "message_container": ["[data-message-author-role]"],
    "role_attribute": ["data-message-author-role"],
    "voice_mic_icon": [
        '[aria-label*="microphone" i]',
        'svg[class*="mic" i]',
        '[data-testid="voice-indicator"]',
    ],
    "voice_duration_text": [
        "span.flex-shrink-0",  # chute, Fase 0 confirma
    ],
    "message_text": [
        "div.markdown",
        "div.whitespace-pre-wrap",
    ],
}


def detect_voice_candidates(raw: dict, threshold: float = 0.5) -> list[str]:
    """Identifica conv IDs com >= threshold% msgs sem text.

    Args:
        raw: dict com {'conversations': {id: conv_dict}}.
        threshold: float 0-1, % minimo de msgs sem text pra flagear.

    Returns:
        Lista de conv IDs candidatos.
    """
    candidates = []
    for conv_id, conv in raw.get("conversations", {}).items():
        mapping = conv.get("mapping", {})
        msg_nodes = [n for n in mapping.values() if n.get("message")]
        if not msg_nodes:
            continue

        no_text_count = sum(1 for n in msg_nodes if not _has_text_content(n))
        ratio = no_text_count / len(msg_nodes)
        if ratio >= threshold:
            candidates.append(conv_id)
            logger.info(f"Voice candidate: {conv_id} ({no_text_count}/{len(msg_nodes)} sem text)")
    return candidates


def _has_text_content(mapping_node: dict) -> bool:
    """True se a msg do node tem parts com texto nao-vazio."""
    msg = mapping_node.get("message") or {}
    content = msg.get("content") or {}
    parts = content.get("parts") or []
    for part in parts:
        if isinstance(part, str) and part.strip():
            return True
        if isinstance(part, dict) and part.get("content_type") == "text" and part.get("text"):
            return True
    return False


DOM_NAVIGATION_THROTTLE_SECONDS = 5


async def capture_voice_dom(page, conv_ids: list[str]) -> dict[str, VoiceCapture]:
    """Abre cada conv_id no Playwright page e extrai msgs voice via DOM scrape.

    Args:
        page: playwright.async_api.Page (ja autenticado via persistent context).
        conv_ids: lista de candidatos a voice.

    Returns:
        dict mapeando conv_id -> VoiceCapture. Convs sem voice_real (sem mic)
        sao omitidas.
    """
    captures: dict[str, VoiceCapture] = {}

    for idx, conv_id in enumerate(conv_ids):
        if idx > 0:
            await asyncio.sleep(DOM_NAVIGATION_THROTTLE_SECONDS)

        url = f"https://chatgpt.com/c/{conv_id}"
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_selector(
                SELECTORS["message_container"][0], timeout=15000
            )

            js = _build_extraction_js()
            raw_msgs = await page.evaluate(js)
        except Exception as exc:
            logger.error(f"Voice DOM capture falhou em {conv_id}: {exc}")
            continue

        messages = [
            VoiceMessage(
                dom_sequence=m.get("dom_sequence", i),
                role=m.get("role", "assistant"),
                text=m.get("text") or "",
                duration_seconds=m.get("duration_seconds"),
                was_voice=bool(m.get("was_voice")),
            )
            for i, m in enumerate(raw_msgs or [])
        ]

        # Se nenhuma msg tem was_voice=True, conv nao era voice de verdade
        if not any(m.was_voice for m in messages):
            logger.info(f"{conv_id} nao tinha icone de mic — provavelmente screenshot, omitido")
            continue

        captures[conv_id] = VoiceCapture(
            conversation_id=conv_id,
            title=None,  # TBD via page.title()
            messages=messages,
        )
        logger.info(f"Voice captured: {conv_id} ({len(messages)} msgs)")

    return captures


def _build_extraction_js() -> str:
    """Monta JS de extracao injetando SELECTORS do Python.

    Seletor principal de cada key usado — fallback chain implementada
    do lado Python (nao do lado JS pra simplificar).
    """
    container_sel = SELECTORS["message_container"][0]
    mic_sel = SELECTORS["voice_mic_icon"][0]
    duration_sel = SELECTORS["voice_duration_text"][0]
    text_sel = SELECTORS["message_text"][0]
    role_attr = SELECTORS["role_attribute"][0]

    return f"""
() => {{
  const messages = [];
  document.querySelectorAll('{container_sel}').forEach((el, idx) => {{
    const role = el.getAttribute('{role_attr}');
    const hasMic = el.querySelector('{mic_sel}') !== null;
    const textEl = el.querySelector('{text_sel}');
    const text = textEl ? textEl.innerText : '';
    let duration = null;
    if (hasMic) {{
      const durEl = el.querySelector('{duration_sel}');
      const durText = durEl ? durEl.innerText : null;
      if (durText) {{
        const match = durText.match(/(\\d+):(\\d+)/);
        if (match) duration = parseInt(match[1]) * 60 + parseInt(match[2]);
      }}
    }}
    messages.push({{
      dom_sequence: idx,
      role: role,
      text: text,
      duration_seconds: duration,
      was_voice: hasMic
    }});
  }});
  return messages;
}}
""".strip()
