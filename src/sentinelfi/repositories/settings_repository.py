from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from sentinelfi.repositories.models import AppSettingRecord


class SettingsRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_settings(self) -> list[AppSettingRecord]:
        statement = select(AppSettingRecord).order_by(AppSettingRecord.key.asc())
        return list(self.session.exec(statement).all())

    def get_setting(self, key: str) -> AppSettingRecord | None:
        return self.session.get(AppSettingRecord, key)

    def upsert_setting(self, *, key: str, value_json: str, updated_at: datetime) -> AppSettingRecord:
        row = self.get_setting(key)
        if row is None:
            row = AppSettingRecord(key=key, value_json=value_json, updated_at=updated_at)
        else:
            row.value_json = value_json
            row.updated_at = updated_at
        self.session.add(row)
        self.session.commit()
        return row
