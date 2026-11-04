#!/usr/bin/env python3
"""
Browser worker for SeleniumBase API

Runs one page fetch in its own process. The API server starts this worker in a
new session, so the worker, chromedriver and every Chrome process share one
process group. When the request ends, the server kills that group. A browser
whose start failed part way, or whose quit() failed, cannot outlive its request.

Usage:
    browser_worker.py REQUEST_JSON RESULT_JSON

REQUEST_JSON holds the fetch options. The worker writes RESULT_JSON with either
{"final_url", "html", "screenshot_uri"} or {"error"}.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger('browser_worker')


def fetch(opts):
    """Load one page in a fresh browser and return its final URL and HTML."""
    from seleniumbase import Driver
    from helpers import reap_abandoned_child_processes

    # Chromium (arm64) runs without UC mode; Chrome runs with it.
    is_chromium = os.path.exists('/usr/bin/chromium-browser')
    logger.info(f'Browser detected: {"Chromium" if is_chromium else "Chrome"}, uc mode: {not is_chromium}')

    driver = None
    try:
        driver = Driver(
            browser='chrome',
            headless=True,
            uc=not is_chromium,
            incognito=opts['incognito'],
        )

        if opts['page_load_timeout'] > 0:
            driver.set_page_load_timeout(opts['page_load_timeout'])

        if opts['viewport_width'] and opts['viewport_height']:
            driver.set_window_size(opts['viewport_width'], opts['viewport_height'])

        driver.get(opts['url'])

        user_scripts_dir = Path(opts['user_scripts_dir'])
        for script_name in opts['user_scripts']:
            script_path = user_scripts_dir / script_name
            if not script_path.exists():
                logger.warning(f'User script not found: {script_name}')
                continue
            try:
                driver.execute_script(script_path.read_text())
                logger.info(f'Executed user script: {script_name}')
            except Exception as e:
                logger.warning(f'Failed to execute user script {script_name}: {e}')
        if opts['user_scripts'] and opts['user_scripts_timeout'] > 0:
            time.sleep(opts['user_scripts_timeout'] / 1000.0)

        if opts['sleep'] > 0:
            time.sleep(opts['sleep'] / 1000.0)

        if opts['scroll_down'] > 0:
            driver.execute_script(f'window.scrollBy(0, {opts["scroll_down"]});')
            # Give time for lazy-loaded content
            time.sleep(0.5)

        screenshot_uri = None
        if opts['screenshot_path']:
            try:
                driver.save_screenshot(opts['screenshot_path'])
                screenshot_uri = f'file://screenshots/{Path(opts["screenshot_path"]).name}'
            except Exception as e:
                logger.warning(f'Failed to save screenshot: {e}')

        return {
            'final_url': driver.current_url,
            'html': driver.page_source,
            'screenshot_uri': screenshot_uri,
        }
    finally:
        if driver:
            try:
                driver.quit()
            except Exception as e:
                logger.warning(f'driver.quit() failed: {e}')
        reap_abandoned_child_processes()


def main(request_path, result_path):
    opts = json.loads(Path(request_path).read_text())
    try:
        result = fetch(opts)
    except Exception as e:
        logger.error(f'Error fetching URL {opts["url"]}: {e}', exc_info=True)
        result = {'error': str(e)}
    Path(result_path).write_text(json.dumps(result))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
