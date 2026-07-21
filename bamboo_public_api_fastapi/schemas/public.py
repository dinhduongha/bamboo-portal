from typing import List, Optional

from pydantic import BaseModel


# --- meta / health ---------------------------------------------------------
class HealthOut(BaseModel):
    status: str
    service: str
    odoo_version: str
    db: Optional[str] = None


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
