# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

from ops.testing import Harness

from charm import MySQLOperatorCharm
from constants import DB_RELATION_NAME

APP_NAME = "mysql-k8s"

SAMPLE_CLUSTER_STATUS = {
    "defaultreplicaset": {
        "topology": {
            "mysql-k8s/0": {
                "address": "2.2.2.2:3306",
                "mode": "r/w",
                "status": "online",
            },
            "mysql-k8s/1": {
                "address": "2.2.2.1:3306",
                "mode": "r/o",
                "status": "gone_away",
            },
            "mysql-k8s/2": {
                "address": "2.2.2.3:3306",
                "mode": "r/0",
                "status": "online",
            },
        }
    }
}


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.patcher = patch("lightkube.core.client.GenericSyncClient")
        self.patcher.start()
        self.harness = Harness(MySQLOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.peer_relation_id = self.harness.add_relation("database-peers", "database-peers")
        self.harness.add_relation_unit(self.peer_relation_id, f"{APP_NAME}/1")
        self.database_relation_id = self.harness.add_relation(DB_RELATION_NAME, "app")
        self.harness.add_relation_unit(self.database_relation_id, "app/0")
        self.charm = self.harness.charm

    def tearDown(self) -> None:
        self.patcher.stop()

    @patch("k8s_helpers.KubernetesHelpers.wait_service_ready")
    @patch("relations.mysql_provider.MySQLProvider._update_endpoints")
    @patch("k8s_helpers.KubernetesHelpers.create_endpoint_services")
    @patch("mysql_k8s_helpers.MySQL.get_mysql_version", return_value="8.0.29-0ubuntu0.20.04.3")
    @patch("mysql_k8s_helpers.MySQL.create_application_database_and_scoped_user")
    @patch(
        "relations.mysql_provider.generate_random_password", return_value="super_secure_password"
    )
    def test_database_requested(
        self,
        _generate_random_password,
        _create_application_database_and_scoped_user,
        _get_mysql_version,
        _create_endpoint_services,
        _update_endpoints,
        _wait_service_ready,
    ):
        # run start-up events to enable usage of the helper class
        self.harness.set_leader(True)
        self.charm.on.config_changed.emit()

        # confirm that the relation databag is empty
        database_relation_databag = self.harness.get_relation_data(
            self.database_relation_id, self.harness.charm.app
        )
        database_relation = self.charm.model.get_relation(DB_RELATION_NAME)
        app_unit = list(database_relation.units)[0]

        # simulate cluster initialized by editing the flag
        self.harness.update_relation_data(
            self.peer_relation_id, self.charm.app.name, {"units-added-to-cluster": "1"}
        )

        self.assertEqual(database_relation_databag, {})
        self.assertEqual(database_relation.data.get(app_unit), {})
        self.assertEqual(database_relation.data.get(self.charm.unit), {})

        # update the app leader unit data to trigger database_requested event
        self.harness.update_relation_data(
            self.database_relation_id, "app", {"database": "test_db"}
        )

        self.assertEqual(
            database_relation_databag,
            {
                "data": '{"database": "test_db"}',
                "password": "super_secure_password",
                "username": f"relation-{self.database_relation_id}",
                "endpoints": "mysql-k8s-primary:3306",
                "version": "8.0.29-0ubuntu0.20.04.3",
                "read-only-endpoints": "mysql-k8s-replicas:3306",
                "database": "test_db",
            },
        )

        _generate_random_password.assert_called_once()
        _create_application_database_and_scoped_user.assert_called_once()
        _get_mysql_version.assert_called_once()
        _create_endpoint_services.assert_called_once()
        _update_endpoints.assert_called_once()
        _wait_service_ready.assert_called_once()
