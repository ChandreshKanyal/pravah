"""Sign-in and roles (policy review, 17 Oct). Firebase Authentication ID tokens (Google sign-in) are verified with
google-auth; roles come from Firestore users/{email}.role, else ADMIN_EMAILS (admin), else DEFAULT_ROLE.

AUTH_REQUIRED=false (the local default) keeps the prototype usable without sign-in: anonymous requests act as
DEFAULT_ROLE and approvals record a typed name marked unverified. Set AUTH_REQUIRED=true on Cloud Run once the Firebase
web app and the Google sign-in provider are enabled (docs/CONFIG.md)."""
import logging
import time

from fastapi import Depends, Header, HTTPException

from app.config import get_settings

log = logging.getLogger(__name__)
ROLES = ["viewer", "field", "analyst", "approver", "admin"]
_cache: dict[str, tuple[float, dict]] = {}


def _verify(token: str) -> dict | None:
    hit = _cache.get(token)
    if hit and hit[0] > time.time():
        return hit[1]
    try:
        from google.auth.transport import requests as greq
        from google.oauth2 import id_token
        claims = id_token.verify_firebase_token(token, greq.Request(), audience=get_settings().google_cloud_project)
    except Exception as e:
        log.info("token rejected: %s", e)
        return None
    if claims:
        _cache[token] = (float(claims.get("exp", time.time() + 300)), claims)
        if len(_cache) > 500:
            _cache.clear()
    return claims


def _role_for(email: str) -> str:
    cfg = get_settings()
    if email and email.lower() in {e.strip().lower() for e in cfg.admin_emails.split(",") if e.strip()}:
        return "admin"
    try:
        from app.services import firestore as fs
        doc = fs.get_doc("users", email.lower()) if email else None
        if doc and doc.get("role") in ROLES:
            return doc["role"]
    except Exception:
        pass
    return cfg.default_role


def current_user(authorization: str | None = Header(None)) -> dict:
    """{email, name, role, verified}; anonymous users get DEFAULT_ROLE with verified=False."""
    if authorization and authorization.lower().startswith("bearer "):
        claims = _verify(authorization.split(" ", 1)[1].strip())
        if claims:
            email = claims.get("email", "")
            return {"email": email, "name": claims.get("name") or email, "role": _role_for(email), "verified": True}
        raise HTTPException(401, "Sign-in expired; please sign in again")
    return {"email": "", "name": "", "role": get_settings().default_role, "verified": False}


def require(role: str):
    """FastAPI dependency: the caller must hold at least `role` (and be signed in when AUTH_REQUIRED)."""
    need = ROLES.index(role)

    def dep(user: dict = Depends(current_user)) -> dict:
        if get_settings().auth_required and not user["verified"]:
            raise HTTPException(401, "Sign in to do this")
        if ROLES.index(user["role"]) < need:
            raise HTTPException(403, f"This needs the {role} role; ask the district administrator")
        return user
    return dep
