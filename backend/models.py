#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API 요청/응답에 쓰이는 pydantic 모델."""

from pydantic import BaseModel


class CommandRequest(BaseModel):
    cmd: str
