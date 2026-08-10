"""Event / forum / job / contact payloads — mirrors of the controllers' builders."""

from typing import List, Optional

from pydantic import BaseModel


# --- event (website_event) -------------------------------------------------
class EventCardOut(BaseModel):
    id: int
    name: str
    subtitle: str = ""
    date_begin: Optional[str] = None
    date_end: Optional[str] = None
    organizer: str = ""
    location: str = ""
    event_type: str = ""
    tags: List[str] = []
    seats_available: Optional[int] = None
    image_url: str = ""
    cover_url: str = ""


class TicketOut(BaseModel):
    id: int
    name: str
    price: float
    seats_available: Optional[int] = None
    description: str = ""


class EventDetailOut(EventCardOut):
    description: str = ""
    website_url: str = ""
    tickets: List[TicketOut] = []


class RegistrationIn(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    ticket_id: Optional[int] = None


class RegistrationOut(BaseModel):
    registration_id: int
    state: str


# --- forum (website_forum) -------------------------------------------------
class ForumOut(BaseModel):
    id: int
    name: str
    description: str = ""
    question_count: int = 0


class QuestionCardOut(BaseModel):
    id: int
    name: str
    forum_id: int
    forum_name: str = ""
    author: str = ""
    create_date: Optional[str] = None
    views: int = 0
    vote_count: int = 0
    answer_count: int = 0
    tags: List[str] = []
    has_accepted: bool = False


class AnswerOut(BaseModel):
    id: int
    content: str = ""
    author: str = ""
    create_date: Optional[str] = None
    vote_count: int = 0
    is_correct: bool = False


class QuestionDetailOut(QuestionCardOut):
    content: str = ""
    answers: List[AnswerOut] = []


class QuestionIn(BaseModel):
    title: Optional[str] = None
    name: Optional[str] = None
    content: str = ""


class AnswerIn(BaseModel):
    content: str = ""


class QuestionCreatedOut(BaseModel):
    question_id: int


class AnswerCreatedOut(BaseModel):
    answer_id: int


# --- job (website_hr_recruitment) ------------------------------------------
class JobCardOut(BaseModel):
    id: int
    name: str
    department: str = ""
    location: str = ""
    no_of_recruitment: int = 0


class JobDetailOut(JobCardOut):
    description: str = ""
    job_details: str = ""
    website_url: str = ""


class ApplicantOut(BaseModel):
    applicant_id: int


# --- contact (website_crm) -------------------------------------------------
class ContactIn(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    subject: str = ""
    message: str = ""


class LeadOut(BaseModel):
    lead_id: int
