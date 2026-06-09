"""Kafka producer wrapper (aiokafka).

A single AIOKafkaProducer is started in the FastAPI lifespan and reused for the
process. Publishing is best-effort: if Kafka was unavailable at startup (or a
send fails), the call logs a warning and returns — a ride request still succeeds
and is durable in Postgres regardless of Kafka. Only ride-request events are
produced; the surge pricing engine is the consumer.
"""
from __future__ import annotations

import json
import logging

from aiokafka import AIOKafkaProducer

from app.core.config import settings

logger = logging.getLogger("app.kafka")


class KafkaPublisher:
    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        """Connect the producer. Raises if the broker is unreachable; the
        lifespan catches that and continues (the app must not crash)."""
        if not settings.kafka_enabled:
            logger.info("Kafka disabled via settings; producer not started")
            return
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k is not None else None,
            acks="all",
            enable_idempotence=True,
        )
        await producer.start()
        self._producer = producer
        logger.info(
            "Kafka producer connected (%s)", settings.kafka_bootstrap_servers
        )

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None
            logger.info("Kafka producer stopped")

    @property
    def available(self) -> bool:
        return self._producer is not None

    async def publish_ride_request(self, event: dict) -> None:
        """Publish a ride-request event to the `ride-requests` topic, keyed by
        ride_id (so a ride's events land on one partition / stay ordered)."""
        if self._producer is None:
            logger.warning(
                "Kafka unavailable; dropping ride-request event %s",
                event.get("event_id"),
            )
            return
        try:
            await self._producer.send_and_wait(
                settings.kafka_ride_requests_topic,
                value=event,
                key=str(event.get("ride_id")),
            )
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Failed to publish ride-request event: %s", exc)


# Process-wide singleton; started/stopped in app.main's lifespan.
kafka_producer = KafkaPublisher()
