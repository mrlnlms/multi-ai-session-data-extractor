"""Debug 2: clica no botao 'Projects' e dumpa o que aparece."""

import asyncio
import json
from playwright.async_api import async_playwright

from src.extractors.chatgpt.auth import get_profile_dir


async def debug():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(get_profile_dir()),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await context.new_page()
        await page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)

        # Clicar no botao com texto exato "Projects"
        clicked = await page.evaluate("""
            () => {
                const cands = Array.from(document.querySelectorAll('button, [role="button"], a[role="button"]'));
                for (const b of cands) {
                    const text = (b.textContent || '').trim();
                    if (text === 'Projects') {
                        const r = b.getBoundingClientRect();
                        if (r.width === 0) continue;
                        b.click();
                        return { clicked: true, tag: b.tagName, href: b.getAttribute('href') };
                    }
                }
                return { clicked: false };
            }
        """)
        print("Click result:", json.dumps(clicked))
        await page.wait_for_timeout(4000)

        info = await page.evaluate("""
            () => {
                const anchors = Array.from(document.querySelectorAll('a[href]'));
                const gpLinks = anchors
                    .map(a => ({
                        href: a.getAttribute('href'),
                        text: (a.textContent || '').trim().slice(0, 60),
                    }))
                    .filter(a => a.href && a.href.includes('g-p-'));
                return {
                    url: window.location.href,
                    title: document.title,
                    total_anchors: anchors.length,
                    gp_link_count: gpLinks.length,
                    gp_samples: gpLinks.slice(0, 60),
                };
            }
        """)

        print(json.dumps(info, indent=2, ensure_ascii=False))

        await context.close()


if __name__ == "__main__":
    asyncio.run(debug())
