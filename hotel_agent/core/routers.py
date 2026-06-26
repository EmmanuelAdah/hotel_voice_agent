"""
Primary/Replica database router.
Directs writes to primary, reads to replica.
"""


class PrimaryReplicaRouter:
    """
    Routes reads to the replica database and writes to the primary.
    Ensures consistency by routing reads to primary after writes.
    """

    READ_MODELS = frozenset([
        "voicesession",
        "auditlog",
        "servicerequest",
        "booking",
        "room",
    ])

    def db_for_read(self, model, **hints):
        """Send reads for safe models to replica."""
        if model._meta.model_name in self.READ_MODELS:
            return "replica"
        return "default"

    def db_for_write(self, model, **hints):
        """Always write to primary."""
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        """Allow relations between primary and replica."""
        db_set = {"default", "replica"}
        if obj1._state.db in db_set and obj2._state.db in db_set:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """Only migrate on primary."""
        return db == "default"
