from datetime import datetime
from typing import Any, Dict

from eNMS.framework import factory, fetch, fetch_all, objectify


class InventoryController:
    def clear_configurations(self, device_id: int) -> None:
        fetch("Device", id=device_id).configurations = {}

    def connection(self, device_id: int) -> dict:
        parameters, device = get_one("Parameters"), fetch("Device", id=device_id)
        cmd = [str(app.path / "applications" / "gotty"), "-w"]
        port, protocol = parameters.get_gotty_port(), request.form["protocol"]
        address = getattr(device, request.form["address"])
        cmd.extend(["-p", str(port)])
        if "accept-once" in request.form:
            cmd.append("--once")
        if "multiplexing" in request.form:
            cmd.extend(f"tmux new -A -s gotty{port}".split())
        if app.config["GOTTY_BYPASS_KEY_PROMPT"]:
            options = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
        else:
            options = ""
        if protocol == "telnet":
            cmd.extend(f"telnet {address}".split())
        elif "authentication" in request.form:
            if request.form["credentials"] == "device":
                login, pwd = device.username, device.password
            else:
                login, pwd = current_user.name, current_user.password
            cmd.extend(f"sshpass -p {pwd} ssh {options} {login}@{address}".split())
        else:
            cmd.extend(f"ssh {options} {address}".split())
        if protocol != "telnet":
            cmd.extend(f"-p {device.port}".split())
        Popen(cmd)
        return {
            "device": device.name,
            "port": port,
            "redirection": app.config["GOTTY_PORT_REDIRECTION"],
            "server_addr": app.config["ENMS_SERVER_ADDR"],
        }

    def update_pools(self, pool_id: str) -> None:
        if pool_id == "all":
            for pool in fetch_all("Pool"):
                pool.compute_pool()
        else:
            fetch("Pool", id=int(pool_id)).compute_pool()
