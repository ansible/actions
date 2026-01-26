#!/usr/bin/env python3
# cspell: ignore updatestamp
"""Replacement for CodeCov GitHub App."""

import datetime
import json
import logging
import os
import sys
import time
from urllib.error import HTTPError
from urllib.request import urlopen

DELAY = 5
MAX_RETRIES = 12
# 5s, 10s, 15s, 20s,...
MIN_AGE_IN_SECONDS = 10
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    start_time = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(seconds=2)
    if os.environ.get("GITHUB_REPOSITORY", "") and os.environ.get(
        "GITHUB_REPOSITORY", ""
    ):
        org, repo = os.environ.get("GITHUB_REPOSITORY", "").split("/")
        pr = os.environ.get("GITHUB_REF_NAME", "").split("/")[0]
    else:
        logger.warning(
            "::warning::GITHUB_REPOSITORY and GITHUB_REF_NAME are needed to determine current pull request."
        )
        sys.exit(0)

    if not pr.isnumeric():
        logger.warning(
            "::warning::Codecov.io status check skipped because a pull request was not detected."
        )
        sys.exit(0)

    retries = 0
    delta_coverage = 0.0
    base_cov = 0.0
    head_cov = 0.0
    sleep = DELAY
    while retries < MAX_RETRIES:
        time.sleep(sleep)
        url = f"https://api.codecov.io/api/v2/github/{org}/repos/{repo}/pulls/{pr}/"
        msg = f"Getting codecov.io status from {url}"
        logger.info(msg)
        error = "Codecov API returned previous stats"
        try:
            with urlopen(url) as response:  # noqa: S310
                response_content = response.read().decode("utf-8")
                data = json.loads(response_content)
                print(data, file=sys.stdout)  # noqa: T201
                base_cov = 0.0
                head_cov = 0.0
                updatestamp = start_time
                if data["updatestamp"]:  # can be None or a string
                    updatestamp = datetime.datetime.fromisoformat(data["updatestamp"])
                if data["base_totals"] is not None:
                    base_cov = data["base_totals"]["coverage"]
                if data["head_totals"] is not None:
                    head_cov = data["head_totals"]["coverage"]
                delta_coverage = head_cov - base_cov
            # It can happen for updatestamp to be updated but head_totals to become
            # None for some time, so we keep retrying until we have something.
            if updatestamp > start_time and head_cov:
                break
        except HTTPError as e:
            error = str(e)
        retries += 1
        sleep = DELAY * (retries + 1)
        msg = f"{error} We will retry the request in {sleep} seconds."
        logger.error(msg)

    msg = f"{abs(delta_coverage):.2f}% ({base_cov:.2f}% on base -> {head_cov:.2f}% on head).\n"
    msg += f"See https://app.codecov.io/gh/{org}/{repo}/pull/{pr} for details."
    if delta_coverage < 0:
        msg = f"Setting coverage check as failed due to coverage going down by {msg}"
        logger.error(msg)
        sys.exit(2)
    msg = f"Setting coverage check as passed due to coverage going up by {msg}"
    logger.info(msg)
    sys.exit(0)
