from typing import List, Optional

from pydantic import BaseModel


# --- meta / health ---------------------------------------------------------
class HealthOut(BaseModel):
    status: str
    service: str
    odoo_version: str
    db: Optional[str] = None


# --- auth ------------------------------------------------------------------
# Field-for-field `portal_auth._user_dict`: the two modes must be swappable
# without the client noticing, so the shapes are compared in test_public_parity.
class MeOut(BaseModel):
    uid: int
    name: str
    login: str
    email: str = ""
    partner_id: int
    share: bool = False


class LoginOut(MeOut):
    access_token: str = ""


class LoginIn(BaseModel):
    login: Optional[str] = None
    email: Optional[str] = None
    password: str = ""


class SignupIn(BaseModel):
    name: str = ""
    email: str = ""
    password: str = ""


class LogoutOut(BaseModel):
    logged_out: bool


# --- courses (website_slides) ---------------------------------------------
class CourseOut(BaseModel):
    id: int
    name: str
    description: str = ""
    total_slides: int = 0
    members_count: int = 0
    cover_url: str = ""


class LessonOut(BaseModel):
    id: int
    name: str
    category: str = ""
    sequence: int = 0


class CourseDetailOut(CourseOut):
    description_html: str = ""
    website_url: str = ""
    lessons: List[LessonOut] = []


# --- blog (website_blog) ---------------------------------------------------
class BlogOut(BaseModel):
    id: int
    name: str
    subtitle: str = ""
    post_count: int = 0


class PostCardOut(BaseModel):
    id: int
    name: str
    subtitle: str = ""
    teaser: str = ""
    blog_id: int
    blog_name: str = ""
    author: str = ""
    post_date: Optional[str] = None
    cover_url: str = ""


class PostDetailOut(PostCardOut):
    content: str = ""
    website_url: str = ""
