import unittest
from unittest.mock import patch

from track1 import deploy_fabric


class FabricDeploymentTests(unittest.TestCase):
    def test_local_file_manifest_includes_all_csvs_and_runtime_scripts(self):
        files = deploy_fabric._local_files()
        names = {name for name, _ in files}
        self.assertEqual(len([name for name in names if name.endswith(".csv")]), 14)
        self.assertIn("load_fabric.py", names)
        self.assertIn("standardization.py", names)
        self.assertIn("create_ontology_fabric_v2.py", names)

    def test_existing_different_file_is_never_overwritten(self):
        with patch.object(
            deploy_fabric,
            "_storage_request",
            side_effect=[(200, b"", {}), (200, b"old content", {})],
        ):
            with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
                deploy_fabric._upload_file(
                    "https://onelake.dfs.fabric.microsoft.com/workspace/lakehouse/Files",
                    "orders.csv",
                    b"new content",
                    "token",
                )

    def test_upload_file_creates_appends_flushes_and_verifies(self):
        with patch.object(
            deploy_fabric,
            "_storage_request",
            side_effect=[
                (404, b"", {}),
                (201, b"", {}),
                (202, b"", {}),
                (200, b"", {}),
                (200, b"", {}),
                (200, b"sample", {}),
            ],
        ) as request:
            result = deploy_fabric._upload_file(
                "https://onelake.dfs.fabric.microsoft.com/workspace/lakehouse/Files",
                "channels.csv",
                b"sample",
                "token",
            )
        self.assertEqual(result, "uploaded")
        self.assertEqual(
            [call.args[0] for call in request.call_args_list],
            ["HEAD", "PUT", "PATCH", "PATCH", "HEAD", "GET"],
        )

    def test_partial_identical_upload_resumes_without_overwriting(self):
        with patch.object(
            deploy_fabric,
            "_storage_request",
            side_effect=[
                (200, b"", {}),
                (200, b"sam", {}),
                (202, b"", {}),
                (200, b"", {}),
                (200, b"", {}),
                (200, b"sample", {}),
            ],
        ) as request:
            result = deploy_fabric._upload_file(
                "https://onelake.dfs.fabric.microsoft.com/workspace/lakehouse/Files",
                "channels.csv",
                b"sample",
                "token",
            )
        self.assertEqual(result, "uploaded")
        self.assertEqual(request.call_args_list[2].args[0], "PATCH")
        self.assertIn("position=3", request.call_args_list[2].args[1])

    def test_runtime_module_replacement_is_explicit_and_limited(self):
        with (
            patch.object(deploy_fabric, "_read_existing_file", return_value=b"old"),
            patch.object(deploy_fabric, "_storage_request", return_value=(200, b"", {})) as request,
            patch.object(deploy_fabric, "_upload_file", return_value="uploaded") as upload,
        ):
            result = deploy_fabric._upload_runtime_file(
                "https://onelake.dfs.fabric.microsoft.com/workspace/lakehouse/Files",
                "standardization.py",
                b"new",
                "token",
                replace_existing=True,
            )
        self.assertEqual(result, "uploaded")
        self.assertEqual(request.call_args.args[0], "DELETE")
        upload.assert_called_once()
        with self.assertRaisesRegex(ValueError, "not allowed"):
            deploy_fabric._upload_runtime_file(
                "https://onelake.dfs.fabric.microsoft.com/workspace/lakehouse/Files",
                "orders.csv",
                b"new",
                "token",
                replace_existing=True,
            )

    def test_deploy_defaults_to_read_only_dry_run(self):
        with (
            patch.object(deploy_fabric, "_local_files", return_value=[("x.csv", b"x")]),
            patch.object(
                deploy_fabric,
                "_workspace",
                return_value=(
                    {"id": "11111111-2222-3333-4444-555555555555", "displayName": "demo"},
                    "existing",
                ),
            ),
            patch.object(
                deploy_fabric,
                "_lakehouse",
                return_value=(
                    {"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
                    "existing",
                ),
            ),
            patch.object(
                deploy_fabric.upload_fabric_notebooks,
                "publish",
                return_value=[{"display_name": "demo", "action": "skip"}],
            ) as publish,
        ):
            result = deploy_fabric.deploy(
                workspace_id="11111111-2222-3333-4444-555555555555",
                fabric_token="fabric-token",
            )
        self.assertEqual(result["mode"], "dry-run")
        self.assertIn("No Fabric resources or OneLake files were changed.", result["note"])
        self.assertFalse(publish.call_args.kwargs["apply"])

    def test_workspace_creation_requires_capacity_id(self):
        with self.assertRaisesRegex(ValueError, "capacity-id"):
            deploy_fabric.deploy(
                workspace_name="New workspace",
                create_workspace=True,
                fabric_token="fabric-token",
            )

    def test_lakehouse_id_guard_precedes_all_deployment_writes(self):
        workspace = "11111111-2222-3333-4444-555555555555"
        expected = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        for lakehouse in (None, {"id": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"}):
            with (
                self.subTest(lakehouse=lakehouse),
                patch.object(deploy_fabric, "_local_files", return_value=[]),
                patch.object(deploy_fabric, "_workspace", return_value=({"id": workspace}, "existing")),
                patch.object(deploy_fabric, "_lakehouse", return_value=(lakehouse, "existing")) as find,
                patch.object(deploy_fabric, "_upload_file") as upload,
                patch.object(deploy_fabric.upload_fabric_notebooks, "publish") as publish,
            ):
                with self.assertRaisesRegex(RuntimeError, "refusing all writes"):
                    deploy_fabric.deploy(
                        workspace_id=workspace,
                        expected_lakehouse_id=expected,
                        apply=True,
                        fabric_token="fabric-token",
                        storage_token="storage-token",
                    )
                self.assertFalse(find.call_args.kwargs["apply"])
                upload.assert_not_called()
                publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
