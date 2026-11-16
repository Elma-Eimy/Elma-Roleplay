"""群聊迁移测试共用旧库与快照。"""
from alembic import command
from tests.support.migrations import group_units as fixtures

HEAD = "b1e2f3a4b5c6"

OLD = fixtures.HEAD


class GroupOperationsMigrationFixture:
    snapshot = fixtures.GroupUnitsMigrationFixture.snapshot

    def setUp(self):
        fixtures.GroupUnitsMigrationFixture.setUp(self)
        command.upgrade(self.config, OLD)
