from typing import Dict, Any, Optional
import uuid
import time
from datetime import datetime
from datamodel import BaseModel, Field

def gen_uuid() -> str:
    """Generate a new UUID."""
    return str(uuid.uuid4().hex)

def time_now() -> int:
    """Get the current time in milliseconds."""
    return int(time.time() * 1000)

class JobRecord(BaseModel):
    """JobRecord.

    Job Record for Background Task Execution.
    """
    task_id: str = Field(default=gen_uuid)
    name: str = None
    status: str = 'pending'
    attributes: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: datetime = Field(default=datetime.now())
    started_at: Optional[int]
    finished_at: Optional[int]
    result: Any = None
    error: Optional[str] = None
    stacktrace: Optional[str] = None

    class Meta:
        strict = True

    def __repr__(self):
        return f"<JobRecord {self.name} ({self.task_id})>"
