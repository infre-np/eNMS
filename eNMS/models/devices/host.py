from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import relationship

from eNMS.database import db, vs
from eNMS.fields import MultipleInstanceField
from eNMS.forms import DeviceForm
from eNMS.fields import HiddenField, IntegerField, SelectField
from eNMS.models.inventory import Device


class Host(Device):
    __tablename__ = "host"
    __mapper_args__ = {"polymorphic_identity": "host"}
    pretty_name = "Host"
    id = db.Column(Integer, ForeignKey("device.id"), primary_key=True)
    priority = db.Column(Integer, default=1)
    devices = relationship(
        "Device", secondary=db.device_host_table, back_populates="hosts"
    )


class HostForm(DeviceForm):
    form_type = HiddenField(default="host")
    icon = SelectField(
        "Icon", choices=list(vs.visualization["icons"].items()), default="host"
    )
    priority = IntegerField("Priority", default=1)
    devices = MultipleInstanceField("Devices", model="device")
    properties = ["priority", "devices"]
