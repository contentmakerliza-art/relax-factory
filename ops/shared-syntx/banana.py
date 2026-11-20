"""Narrow Playwright adapter for the existing, private SYNTX Chromium.

Staged only. Requires explicit deployment and a live UI acceptance test.
No arbitrary URLs, JavaScript supplied by callers, model selection or shell.
"""
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright
from references import reference_paths

BANANA_URL = "https://syntx.ai/ru/image/banana"


def permitted_page(url):
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.netloc == "syntx.ai"
            and re.fullmatch(r"/ru/image/banana(?:/[A-Za-z0-9-]+)?/?", parsed.path) is not None)


def collect_result(page, message, job_id, output_dir):
    """Download the existing result only. Never clicks generation or retry."""
    if not re.fullmatch(r"[0-9a-f]{32}", job_id) or not permitted_page(page.url):
        raise ValueError("Invalid result context")
    with page.expect_download(timeout=60000) as download_info:
        message.locator('[data-cy="download-file-btn"]').click()
    download = download_info.value
    suffix = Path(download.suggested_filename).suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise RuntimeError("Unexpected output format")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    target = output / (job_id + suffix)
    download.save_as(str(target))
    if not 100 < target.stat().st_size <= 25_000_000:
        raise RuntimeError("Unexpected output size")
    from PIL import Image
    with Image.open(target) as image:
        width, height = image.size
        image.verify()
    if not 100 <= min(width, height) <= max(width, height) <= 8192:
        raise RuntimeError("Unexpected image dimensions")
    return {"file": target.name, "width": width, "height": height}


def _run_with_browser_lease(job, queue, output_dir, *, cdp="http://127.0.0.1:9222", prepare_only=False):
    from browser_lease import browser_lease
    with browser_lease():
        return _run_unlocked(job, queue, output_dir, cdp=cdp, prepare_only=prepare_only)


run = _run_with_browser_lease


def _run_unlocked(job, queue, output_dir, *, cdp="http://127.0.0.1:9222", prepare_only=False):
    """Run one claimed job; disconnects after submission never retry generation."""
    if cdp != "http://127.0.0.1:9222":
        raise ValueError("Only the isolated local browser is permitted")
    job_id = job['id']
    state = "preparing"
    page = None
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp, timeout=15000, artifacts_dir="/downloads")
        try:
            if len(browser.contexts) != 1:
                raise RuntimeError("Expected exactly one isolated SYNTX profile")
            pages = browser.contexts[0].pages
            if len(pages) != 1 or urlsplit(pages[0].url).netloc != "syntx.ai":
                raise RuntimeError("Expected one dedicated SYNTX tab")
            page = pages[0]

            def guard(route):
                request = route.request
                if request.is_navigation_request() and not permitted_page(request.url):
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", guard)
            page.set_default_timeout(20000)
            page.goto(BANANA_URL, wait_until="domcontentloaded")
            prompt = page.get_by_placeholder("Напишите ваш промпт...", exact=True)
            prompt.wait_for(state="visible")
            if not permitted_page(page.url):
                raise RuntimeError("SYNTX sign-in or page verification required")
            visible_models = page.get_by_role("combobox").evaluate_all(
                "es => es.filter(e=>e.getBoundingClientRect().width>0).map(e=>e.closest('.el-select')?.innerText.trim())")
            model_button = page.locator('[data-cy="ai-select-menu-btn"]')
            expected_model = job['payload'].get('model', 'Banana 2')
            expected_resolution = job['payload'].get('resolution', '2K')
            if (expected_model, expected_resolution) not in (('Banana 2', '2K'), ('Banana Pro', '4K')):
                raise RuntimeError('Unsupported preparation profile')
            if not prepare_only and expected_model != 'Banana 2':
                raise RuntimeError('Pro generation is not authorized; preparation only')
            selected_version = page.locator('[data-cy="ai-model-select-dropdown-menu"]')
            refreshed_model = (model_button.count() == 1
                and model_button.inner_text().strip() == 'Nano Banana'
                and selected_version.count() == 1 and selected_version.inner_text().strip() == expected_model)
            legacy_model = (expected_model == 'Banana 2' and 'Nano Banana' in visible_models and 'Banana 2' in visible_models)
            if not refreshed_model and not legacy_model:
                raise RuntimeError("Ordinary Nano Banana / Banana 2 is not selected")
            form = page.locator("form").filter(has=prompt)
            ratio = form.locator(".form-settings__badge").filter(has=page.locator(".form-settings__ratio-box"))
            ratio.locator(".el-select__wrapper").click()
            page.get_by_role("option", name=re.compile(r"^" + re.escape(job['payload']['aspect_ratio']) + r"(?:\s|$)")).click()
            if job['payload']['aspect_ratio'] not in ratio.inner_text():
                raise RuntimeError("Aspect ratio did not change")
            if not form.locator(".form-settings__badge").filter(has_text=expected_resolution).count():
                raise RuntimeError("Expected 2K resolution; review settings")
            if form.locator(".uploaded-files__list img").count():
                raise RuntimeError("Unexpected reference uploads; review page")
            references = reference_paths(job['payload'].get('reference_ids', []), Path(output_dir) / 'references')
            if references:
                upload = form.locator('input[type="file"]')
                if upload.count() != 1:
                    raise RuntimeError('Expected one reference upload input')
                if len(references) > 1 and upload.get_attribute('multiple') is None:
                    raise RuntimeError('SYNTX upload does not support multiple references')
                upload.set_input_files([{'name': f'reference-{i+1}.png', 'mimeType': 'image/png', 'buffer': path.read_bytes()}
                                        for i, path in enumerate(references)], timeout=60000)
                # The reference must really be visible before a chargeable click.
                page.wait_for_function("n => {const imgs=[...document.querySelectorAll('form .uploaded-files__list img')]; return imgs.length===n && imgs.every(i=>i.complete && i.naturalWidth>0)}", arg=len(references), timeout=60000)
            prompt.fill(job['payload']['prompt'])
            submit = form.locator("button.send-actions__send")
            if not submit.is_enabled():
                raise RuntimeError("Generation button is disabled")
            if prepare_only:
                return {"ready": True, "model": expected_model, "aspect_ratio": ratio.inner_text().strip(), "resolution": expected_resolution, "reference_count": len(references), "cost": form.locator(".send-actions__cost").inner_text().strip()}
            cost = form.locator('.send-actions__cost').inner_text().strip()
            if not 0 < float(cost.replace(',', '.')) <= 3:
                raise RuntimeError('Expected Banana 2 cost at most 3 tokens; review price')
            before = page.locator(".bot-image-message").count()
            # Persist before any chargeable click, including timeout/connection loss.
            queue.transition(job_id, "preparing", "submitted")
            state = "submitted"
            submit.click()
            page.wait_for_function("n => document.querySelectorAll('.bot-image-message').length > n", arg=before, timeout=90000)
            message = page.locator(".bot-image-message").nth(before)
            image = message.locator("img.bot-image-item__image")
            image.wait_for(state="visible", timeout=300000)
            if image.count() != 1:
                raise RuntimeError("Expected one generated image; review result")
            result = collect_result(page, message, job_id, output_dir)
            queue.transition(job_id, "submitted", "completed", result={
                **result, "model": "Banana 2", "aspect_ratio": job['payload']['aspect_ratio'],
                "reference_count": len(references), "cost_tokens": cost,
                "syntx_chat_url": page.url,
            })
            state = "completed"
        except Exception:
            if prepare_only:
                raise
            # Do not put cookies, browser internals or signed asset URLs in errors.
            if state == "preparing":
                queue.transition(job_id, "preparing", "failed", error="SYNTX preparation failed; inspect browser")
            elif state == "submitted":
                queue.transition(job_id, "submitted", "uncertain", error="Check SYNTX history; generation was not repeated")
            raise RuntimeError("SYNTX task requires inspection") from None
        finally:
            # Closing the CDP client disconnects it; the persistent Chromium stays.
            browser.close()
