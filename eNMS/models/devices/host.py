from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import relationship

from eNMS.database import db, vs
from eNMS.forms import DeviceForm
from eNMS.fields import HiddenField, StringField, SelectField
from eNMS.models.inventory import Device


class Host(Device):
    __tablename__ = "host"
    __mapper_args__ = {"polymorphic_identity": "host"}
    pretty_name = "Host"
    id = db.Column(Integer, ForeignKey("device.id"), primary_key=True)
    serial_number = db.Column(db.SmallString)


class HostForm(DeviceForm):
    form_type = HiddenField(default="host")
    icon = SelectField(
        "Icon", choices=list(vs.visualization["icons"].items()), default="host"
    )
    serial_number = StringField("Serial Number")
    properties = ["serial_number"]
