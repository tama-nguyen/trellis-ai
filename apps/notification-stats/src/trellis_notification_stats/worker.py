"""Plugin entry point (``trellis.workers`` -> ``notification-stats``)."""

from typing import Final

from pydantic import SecretStr

from trellis_core.json_types import JsonObject
from trellis_core.plugins import SupportStatus, plugin
from trellis_events.generated import notification_published_v1
from trellis_events.inbox.memory import InMemoryInboxGuard
from trellis_events.worker import WorkerContext, WorkerDefinition, WorkerParts
from trellis_notification_stats.action import CountPublishedNotifications
from trellis_notification_stats.config import NotificationStatsConfig, StoreKind
from trellis_notification_stats.store import InMemoryCounterStore

WORKER_NAME: Final = "notification-stats"


@plugin(
    name=WORKER_NAME,
    description="Counts published notifications per audience; idempotent via the inbox.",
    config=NotificationStatsConfig,
    status=SupportStatus.INCUBATING,
    capabilities=frozenset({"inbox", "postgres-store"}),
)
class NotificationStatsWorker(WorkerDefinition):
    def build(self, worker_config: JsonObject, ctx: WorkerContext) -> WorkerParts:
        config = NotificationStatsConfig.model_validate(worker_config)
        event_types = frozenset({notification_published_v1.EVENT_TYPE})
        consumer = ctx.settings.consumer_name
        store_kind, dsn = config.resolve(ctx.database_url)
        if store_kind == StoreKind.POSTGRES and dsn is not None:
            return self._postgres(dsn, config.pool_size, ctx, event_types)
        inbox = InMemoryInboxGuard(consumer)
        store = InMemoryCounterStore()
        inbox.commit_listeners.append(store)
        return WorkerParts(
            event_types=event_types,
            action=CountPublishedNotifications(inbox, store, ctx.report),
            status=lambda: {"counters": dict(store.snapshot())},
        )

    @staticmethod
    def _postgres(
        dsn: SecretStr, pool_size: int, ctx: WorkerContext, event_types: frozenset[str]
    ) -> WorkerParts:
        # Imported lazily: psycopg is only needed (and installed) for the postgres store.
        from trellis_events.inbox.postgres import PostgresInboxGuard
        from trellis_notification_stats.postgres_store import PostgresCounterStore

        inbox = PostgresInboxGuard.connect(dsn, ctx.settings.consumer_name, max_size=pool_size)
        store = PostgresCounterStore(inbox.pool)
        return WorkerParts(
            event_types=event_types,
            action=CountPublishedNotifications(inbox, store, ctx.report),
            status=lambda: {"counters": dict(store.snapshot())},
            ready=inbox.check,
            close=inbox.close,
        )
