# -*- coding: utf-8 -*-
"""만들어 낸 쪽의 <script> 가 문법적으로 성한지 본다. 쓰기 전에 부른다.

왜 필요한가
  2026-10-07 에 각주 안에 홑따옴표를 넣었다가('닥터 코퍼') 바깥 문자열이
  거기서 닫혔다. 자바스크립트가 통째로 문법 오류가 되어 **그림이 하나도
  그려지지 않았다.** 그런데 빌드는 성공으로 끝났다 — 값은 멀쩡히 들어갔고
  index.html 도 정상으로 써졌다. 깨진 것은 브라우저가 읽는 순간이었다.

  파이썬 쪽 점검(범위 검사·빠진 계열 세기)은 전부 '값'을 본다. 값이 맞아도
  쪽이 죽을 수 있다는 것을 그날 알았다. 소장님이 열어 보시지 않았으면
  다음 날 아침까지 그대로 나갔다.

왜 글자를 세지 않는가
  처음에는 따옴표·괄호의 짝을 세는 식으로 짰는데 **바로 그 고장을 못
  잡았다.** `'…움직여 '닥터 코퍼' 라고…'` 는 따옴표가 짝수다. 숫자로는
  멀쩡하고 문법만 깨져 있다. 그래서 진짜 해석기를 쓴다.

  esprima 는 순수 파이썬이라 러너에 Node 를 깔지 않아도 된다.

esprima 가 없으면
  빌드를 세우지 않는다. 점검 장치가 없다고 쪽을 못 올리게 하는 것은
  본말이 뒤집힌 것이다. 대신 '[어긋남]' 으로 크게 적어 ops 와 주간
  점검까지 흘려보낸다 — 검사가 조용히 꺼져 있는 것이 가장 나쁘다.
"""

from __future__ import annotations

import re

SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.S | re.I)
IS_DATA = re.compile(r'type\s*=\s*["\']application/json["\']', re.I)


class ScriptError(RuntimeError):
    """쪽의 자바스크립트가 깨졌다. 올리면 안 된다."""


def _parser():
    try:
        import esprima                                   # noqa: PLC0415
    except ImportError:
        return None
    return esprima


def check_html(html: str) -> tuple[list[str], bool]:
    """(문제 목록, 실제로 검사했는가) 를 돌려준다."""
    esprima = _parser()
    if esprima is None:
        return [], False

    problems: list[str] = []
    for n, m in enumerate(SCRIPT.finditer(html), 1):
        attrs, code = m.group(1), m.group(2)
        if IS_DATA.search(attrs) or not code.strip():
            continue                      # 자료 덩어리와 바깥 라이브러리
        try:
            esprima.parseScript(code)
        except Exception as exc:          # noqa: BLE001 — 해석기가 내는 것은 무엇이든 고장이다
            line = getattr(exc, "lineNumber", None)
            where = f"{n}번째 <script>" + (f" {line}번째 줄" if line else "")
            hint = ""
            if line:
                rows = code.split("\n")
                if 0 < line <= len(rows):
                    hint = f"\n      → {rows[line - 1].strip()[:90]}"
            problems.append(f"{where}: {exc}{hint}")
    return problems, True


def must_be_sound(html: str, log=print) -> None:
    """깨졌으면 예외를 올린다. 쪽을 쓰기 **전에** 부른다."""
    problems, checked = check_html(html)
    if not checked:
        log("  [어긋남] esprima 가 없어 자바스크립트를 검사하지 못했다 "
            "— requirements.txt 를 확인할 것")
        return
    if problems:
        raise ScriptError(
            "쪽의 자바스크립트가 깨졌다 — 그림이 하나도 안 그려진다:\n  "
            + "\n  ".join(problems))
    log("  자바스크립트 문법 이상 없음")
