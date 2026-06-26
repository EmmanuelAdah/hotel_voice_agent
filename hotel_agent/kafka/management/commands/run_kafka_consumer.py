"""
Django management command to run the Kafka consumer.
Usage: python manage.py run_kafka_consumer
"""
import signal
import logging
from django.core.management.base import BaseCommand
from django.conf import settings

logger = logging.getLogger("hotel_agent.kafka")


class Command(BaseCommand):
    help = "Run the Kafka consumer for Hotel Voice Agent events"

    def add_arguments(self, parser):
        parser.add_argument(
            "--group-id",
            type=str,
            default=None,
            help="Override Kafka consumer group ID",
        )
        parser.add_argument(
            "--topics",
            nargs="+",
            type=str,
            default=None,
            help="Override topics to consume (space-separated)",
        )

    def handle(self, *args, **options):
        from hotel_agent.kafka.producer_consumer import KafkaConsumerService, setup_kafka_topics
        from hotel_agent.kafka.handlers import register_all_handlers

        # Ensure topics exist
        self.stdout.write("Setting up Kafka topics...")
        setup_kafka_topics()

        topics = options.get("topics") or list(settings.KAFKA_TOPICS.values())
        group_id = options.get("group_id")

        self.stdout.write(f"Starting consumer on topics: {topics}")
        consumer = KafkaConsumerService(topics=topics, group_id=group_id)
        register_all_handlers(consumer)

        # Graceful shutdown on SIGTERM/SIGINT
        def handle_shutdown(signum, frame):
            self.stdout.write("\nShutting down Kafka consumer...")
            consumer.stop()

        signal.signal(signal.SIGTERM, handle_shutdown)
        signal.signal(signal.SIGINT, handle_shutdown)

        try:
            consumer.start()
        except Exception as e:
            self.stderr.write(f"Consumer error: {e}")
            raise
        finally:
            self.stdout.write("Kafka consumer stopped.")
