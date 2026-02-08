"""Compatibility router exports.

Routers have been reorganized under app.api.v1.*.
This module re-exports router modules to avoid breaking older imports.
"""

from app.api.v1.shared import auth, users
from app.api.v1.inventory import dashboard, events, movements, outgoings, parts, receivings, requests

__all__ = [
	"auth",
	"users",
	"dashboard",
	"events",
	"movements",
	"outgoings",
	"parts",
	"receivings",
	"requests",
]
