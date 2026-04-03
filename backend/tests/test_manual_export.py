import asyncio
import io
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.deps import get_db
from app.db.engine import engine
from app.main import app
from app.models.subject import Subject

client = TestClient(app)

def test_workflow():
    with Session(engine) as session:
        # 1. Create a subject
        response = client.post("/api/v1/subjects/add", json={"name": "Test Subject For Export", "description": "Testing export import"})
        assert response.status_code == 200, response.text
        subject_id = response.json()["data"]["subject_id"]
        
        # 2. Update the subject
        response = client.post("/api/v1/subjects/update", json={"subject_id": subject_id, "name": "Renamed Subject", "description": ""})
        assert response.status_code == 200, response.text
        assert response.json()["data"]["name"] == "Renamed Subject"

        # 3. Export preview
        response = client.post(f"/api/v1/subjects/{subject_id}/export/preview")
        assert response.status_code == 200, response.text
        
        # 4. Export
        response = client.post(f"/api/v1/subjects/{subject_id}/export", json={"include_raw_files": True, "include_chat_history": True, "include_exam_history": True, "include_profile": True})
        assert response.status_code == 200, response.text
        export_file_content = response.content

        # 5. Import as new subject
        # Use multipart/form-data
        files = {"file": ("exported.atmx", export_file_content, "application/octet-stream")}
        data = {"new_subject_name": "Imported Subject"}
        response = client.post("/api/v1/subjects/import", files=files, data=data)
        assert response.status_code == 200, response.text
        new_subject_id = response.json()["data"]["subject_id"]
        
        assert new_subject_id != subject_id
        
        # Verify db
        db_sub = session.exec(select(Subject).where(Subject.slug == new_subject_id)).first()
        assert db_sub is not None
        assert db_sub.name == "Imported Subject"

        print("SUCCESS! All export/import/rename endpoints work flawlessly.")

if __name__ == "__main__":
    test_workflow()
