from __future__ import annotations

from sqlalchemy.orm import Session

from app.runtime.contracts import RuntimeStatusContract, runtime_contract_defaults, runtime_surfaces
from app.services.central_brain_runtime import CentralBrainRuntime, SnapshotWatchdogService


class BlumRuntimeFacade:
    """Application runtime boundary.

    Runtime state is operational metadata: readiness, snapshots, queues and
    surfaces. It must not create financial decisions or own alpha logic.
    """

    def status(self, db: Session) -> dict:
        defaults = runtime_contract_defaults()
        contract = RuntimeStatusContract(
            version=defaults["version"],
            feature_set=defaults["feature_set"],
            owns_intelligence=False,
            responsibilities=defaults["responsibilities"],
            primary_surfaces=runtime_surfaces(),
            developer_surfaces=defaults["developer_surfaces"],
            runtime_state={
                "central_brain": CentralBrainRuntime().state(db),
                "snapshots": SnapshotWatchdogService().health(db, queue_rebuild=False),
            },
            policy="BLUM Runtime observes and renders Engine knowledge. It never owns financial intelligence.",
        )
        return contract.to_dict()

    def operating_state(self, db: Session) -> dict:
        from app.runtime.operating_state import OperatingStateService

        return OperatingStateService().read(db)

    def contract(self) -> dict:
        defaults = runtime_contract_defaults()
        return {
            **defaults,
            "primary_surfaces": [surface.to_dict() for surface in runtime_surfaces()],
            "policy": "Runtime can be replaced by web, mobile, CLI, bot or API clients without changing Engine logic.",
        }
