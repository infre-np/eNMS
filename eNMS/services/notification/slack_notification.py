from slackclient import SlackClient
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text
from typing import Optional
from wtforms import HiddenField, StringField
from wtforms.widgets import TextArea

from eNMS.controller import controller
from eNMS.database.dialect import LargeString, SmallString
from eNMS.forms.automation import ServiceForm
from eNMS.forms.fields import SubstitutionField
from eNMS.models.automation import Run, Service
from eNMS.models.inventory import Device


class SlackNotificationService(Service):

    __tablename__ = "SlackNotificationService"

    id = Column(Integer, ForeignKey("Service.id"), primary_key=True)
    has_targets = Column(Boolean, default=False)
    channel = Column(SmallString, default="")
    token = Column(SmallString, default="")
    body = Column(LargeString, default="")

    __mapper_args__ = {"polymorphic_identity": "SlackNotificationService"}

    def job(self, run: "Run", payload: dict, device: Optional[Device] = None) -> dict:
        slack_client = SlackClient(run.token or controller.slack_token)
        channel = run.sub(run.channel, locals()) or controller.slack_channel
        run.log("info", f"Sending Slack notification on {channel}")
        result = slack_client.api_call(
            "chat.postMessage", channel=channel, text=run.sub(run.body, locals())
        )
        return {"success": True, "result": str(result)}


class SlackNotificationForm(ServiceForm):
    form_type = HiddenField(default="SlackNotificationService")
    channel = SubstitutionField()
    token = StringField()
    body = SubstitutionField(widget=TextArea(), render_kw={"rows": 5})
