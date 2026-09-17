import os
from datetime import date
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from home_operator import store

WEB_DIR = Path(__file__).parent / "web"

HOME = store.load_home()

# In-memory for now: one home, one repair at a time, reset on restart.
# Week 3 moves both to DynamoDB, keyed per customer.
SESSIONS: dict = {}

mcp = MCPServer(
    name="home-operator",
    title="Home Operator",
    version="0.1.0",
    instructions=(
        "Hands-free help with the appliances in this home: what each one is, "
        "which replacement parts it takes, and what maintenance is due."
    ),
)

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


@mcp.tool(
    title="Look up an appliance",
    description=(
        "Look up one appliance in this home. Returns its model number, warranty status, "
        "the replacement parts it takes (such as filter sizes), and its most recent service. "
        "If nothing matches, or several appliances match, returns the options to ask about."
    ),
    annotations=READ_ONLY,
)
def get_appliance(
    appliance: Annotated[
        str,
        Field(description='The appliance as the person said it, e.g. "furnace", "the fridge", or "kitchen dishwasher".'),
    ],
) -> dict:
    return store.describe_appliance(HOME, appliance, date.today())


@mcp.tool(
    title="Check maintenance due",
    description=(
        "List home maintenance that is overdue, and tasks coming due soon, across every "
        "appliance in this home. Overdue items are sorted most overdue first."
    ),
    annotations=READ_ONLY,
)
def get_maintenance_due(
    within_days: Annotated[
        int,
        Field(description="How many days ahead to look for upcoming tasks. Overdue tasks are always included.", ge=0, le=365),
    ] = 30,
) -> dict:
    return store.maintenance_due(HOME, date.today(), within_days)


@mcp.tool(
    title="Diagnose a symptom",
    description=(
        "Given an appliance and what it is doing wrong, return the likely causes in order, "
        "with the repair available for each and when that repair was last done. "
        "Use this before starting a repair."
    ),
    annotations=READ_ONLY,
)
def diagnose_symptom(
    appliance: Annotated[str, Field(description='Which appliance, e.g. "dishwasher" or "the furnace".')],
    symptom: Annotated[str, Field(description='What it is doing, in the person\'s own words, e.g. "it will not drain".')],
) -> dict:
    return store.diagnose_symptom(HOME, appliance, symptom, date.today())


@mcp.tool(
    title="Start a repair",
    description=(
        "Begin a step-by-step repair and return the first step, along with the tools needed, "
        "a safety note and how many steps there are. Keeps the person's place until they finish."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
def start_repair(
    appliance: Annotated[str, Field(description='Which appliance, e.g. "dishwasher".')],
    task: Annotated[str, Field(description='The repair to walk through, e.g. "clean the filter".')],
) -> dict:
    return store.start_repair(HOME, SESSIONS, appliance, task, date.today())


@mcp.tool(
    title="Move through a repair",
    description=(
        "Move through the repair already in progress. Use next to advance, back to return to the "
        "previous step, and repeat to hear the current step again. Finishing the last step records "
        "the service automatically."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
def navigate_repair(
    action: Annotated[str, Field(description='One of "next", "back" or "repeat".')] = "next",
) -> dict:
    return store.navigate_repair(HOME, SESSIONS, action, date.today())


@mcp.tool(
    title="Log completed service",
    description=(
        "Record that maintenance or a repair was done today, so future overdue checks are accurate. "
        "Returns when the task is next due."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
def log_service(
    appliance: Annotated[str, Field(description='Which appliance, e.g. "fridge".')],
    task: Annotated[str, Field(description='What was done, e.g. "replaced the water filter".')],
    notes: Annotated[str | None, Field(description="Anything worth remembering next time.")] = None,
) -> dict:
    return store.log_service(HOME, appliance, task, date.today(), notes)


def build_app():
    """The MCP endpoint at /mcp, plus the simulated Alexa+ front end at /sim."""
    app = mcp.streamable_http_app(stateless_http=True, json_response=True)
    app.router.routes.append(
        Mount("/sim", app=StaticFiles(directory=WEB_DIR, html=True), name="sim")
    )
    return app


def main() -> None:
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"MCP endpoint  http://{host}:{port}/mcp")
    print(f"Simulator     http://{host}:{port}/sim/")
    uvicorn.run(build_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
