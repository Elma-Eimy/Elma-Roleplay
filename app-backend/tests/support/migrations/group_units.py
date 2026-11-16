"""群聊迁移测试共用旧库与快照。"""
from alembic import command
from tests.support.migrations import group_round as fixtures

HEAD = "b0d1e2f3a4b5"

OLD = fixtures.HEAD


class GroupUnitsMigrationFixture:
    def setUp(self):
        fixtures.GroupRoundMigrationFixture.setUp(self)
        command.upgrade(self.config, OLD)
        fixtures.GroupRoundMigrationFixture.seed(self)

    snapshot = fixtures.GroupRoundMigrationFixture.snapshot
