from flask import (
    abort,
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_login import current_user, login_user, logout_user
from functools import wraps
from logging import info
from os import listdir
from typing import Any, Callable
from werkzeug.wrappers import Response

from eNMS import app
from eNMS.database import Session
from eNMS.database.functions import fetch, handle_exception
from eNMS.forms import form_actions, form_classes, form_postprocessing, form_templates
from eNMS.forms.administration import LoginForm
from eNMS.forms.automation import ServiceTableForm
from eNMS.models import models
from eNMS.properties.diagram import type_to_diagram_properties
from eNMS.properties.table import (
    filtering_properties,
    table_fixed_columns,
    table_properties,
)


blueprint = Blueprint("blueprint", __name__, template_folder="../templates")


def monitor_requests(function):
    @wraps(function)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            client_address = request.environ.get(
                "HTTP_X_FORWARDED_FOR", request.environ["REMOTE_ADDR"]
            )
            app.log(
                "warning",
                (
                    f"Unauthorized {request.method} request from "
                    f"'{client_address}' calling the endpoint '{request.url}'"
                ),
            )
            return redirect(url_for("blueprint.route", page="login"))
        else:
            return function(*args, **kwargs)

    return decorated_function


@blueprint.route("/")
def site_root():
    return redirect(url_for("blueprint.route", page="login"))


@blueprint.route("/<path:_>")
@monitor_requests
def get_requests_sink(_):
    abort(404)


@blueprint.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        try:
            user = app.authenticate_user(**request.form.to_dict())
            if user:
                login_user(user)
                return redirect(url_for("blueprint.route", page="dashboard"))
            else:
                abort(403)
        except Exception as e:
            info(f"Authentication failed ({str(e)})")
            abort(403)
    if not current_user.is_authenticated:
        login_form = LoginForm(request.form)
        authentication_methods = [("Local User",) * 2]
        if app.use_ldap:
            authentication_methods.append(("LDAP Domain",) * 2)
        if app.use_tacacs:
            authentication_methods.append(("TACACS",) * 2)
        login_form.authentication_method.choices = authentication_methods
        return render_template("login.html", login_form=login_form)
    return redirect(url_for("blueprint.route", page="dashboard"))


@blueprint.route("/logout")
@monitor_requests
def logout():
    logout_user()
    return redirect(url_for("blueprint.route", page="login"))


@blueprint.route("/administration")
@monitor_requests
def administration():
    return render_template(
        f"pages/administration.html",
        **{
            "endpoint": "administration",
            "folders"dir(app.path / "projects" / "migrations"),
        },
    )


@blueprint.route("/dashboard")
@monitor_requests
def dashboard():
    return render_template(
        f"pages/dashboard.html",
        **{"endpoint": "dashboard", "properties": type_to_diagram_properties},
    )


@blueprint.route("/table/<table_type>")
@monitor_requests
def table(table_type):
    kwargs = {
        "endpoint": f"table/{table_type}",
        "fixed_columns": table_fixed_columns[table_type],
        "type": table_type,
    }
    if table_type == "service":
        service_table_form = ServiceTableForm(request.form)
        service_table_form.services.choices = sorted(
            (service, service)
            for service in models
            if service != "service" and service.endswith("service")
        )
        kwargs["service_table_form"] = service_table_form
    return render_template(f"pages/table.html", **kwargs)


@blueprint.route("/view/<view_type>")
@monitor_requests
def view(view_type):
    return render_template(
        f"pages/view.html", **{"endpoint": "view", "view_type": view_type}
    )


@blueprint.route("/workflow_builder")
@monitor_requests
def workflow_builder():
    workflow = fetch("workflow", allow_none=True, id=session.get("workflow", None))
    service_table_form = ServiceTableForm(request.form)
    service_table_form.services.choices = sorted(
        (service, service)
        for service in models
        if service != "service" and service.endswith("service")
    )
    return render_template(
        f"pages/workflow_builder.html",
        service_table_form=service_table_form,
        **{
            "endpoint": "workflow_builder",
            "workflow": workflow.serialized if workflow else None,
        },
    )


@blueprint.route("/calendar/<calendar_type>")
@monitor_requests
def calendar(calendar_type):
    return render_template(
        f"pages/calendar.html",
        **{"calendar_type": calendar_type, "endpoint": "calendar"},
    )


@blueprint.route("/form/<form_type>")
@monitor_requests
def form(form_type):
    kwargs = (
        {"fixed_columns": table_fixed_columns[form_type], "type": form_type}
        if form_type == "result"
        else {}
    )
    return render_template(
        f"forms/{form_templates.get(form_type, 'base')}_form.html",
        **{
            "endpoint": f"form/{form_type}",
            "action": form_actions.get(form_type),
            "form": form_classes[form_type](request.form),
            "form_type": form_type,
            **kwargs,
        },
    )


@blueprint.route("/view_job_results/<int:id>")
@monitor_requests
def view_job_results(id):
    result = fetch("run", id=id).result().result
    return f"<pre>{app.str_dict(result)}</pre>"


@blueprint.route("/download_configuration/<id>")
@monitor_requests
def download_configuration(id):
    configuration = fetch("configuration", id=id)
    filename = f"{configuration.device_name}-{app.strip_all(configuration.runtime)}"
    return Response(
        (f"{line}\n" for line in configuration.configuration.splitlines()),
        mimetype="text/plain",
        headers={
            "Content-Disposition": f"attachment;filename={filename}.txt"
        },
    )


@blueprint.route("/", methods=["POST"])
@blueprint.route("/<path:page>", methods=["POST"])
@monitor_requests
def route(page):
    f, *args = page.split("/")
    if f not in app.valid_post_endpoints:
        return jsonify({"error": "Invalid POST request."})
    form_type = request.form.get("form_type")
    if f in ("table_filtering", "view_filtering", "multiselect_filtering"):
        result = getattr(app, f)(*args, request.form)
    elif form_type:
        form = form_classes[form_type](request.form)
        if not form.validate_on_submit():
            return jsonify({"invalid_form": True, **{"errors": form.errors}})
        result = getattr(app, f)(*args, **form_postprocessing(request.form))
    else:
        result = getattr(app, f)(*args)
    try:
        Session.commit()
        return jsonify(result)
    except Exception as exc:
        raise exc
        Session.rollback()
        if app.config_mode == "Debug":
            raise
        return jsonify({"error": handle_exception(str(exc))})
