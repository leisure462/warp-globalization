from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from warpl10n.patch_update import UpdatePatchError, run_patch_update


OSS_RS = """use anyhow::Result;
use warp_core::{
    channel::{Channel, ChannelConfig, ChannelState, OzConfig, WarpServerConfig},
    AppId,
};

fn main() -> Result<()> {
    let mut state = ChannelState::new(
        Channel::Oss,
        ChannelConfig {
            telemetry_config: None,
            crash_reporting_config: None,
            autoupdate_config: None,
            mcp_static_config: None,
        },
    );
    Ok(())
}
"""

AUTOUPDATE_MOD_RS = """use rand::Rng as _;
use std::sync::Arc;
use std::time::Duration;

use self::channel_versions::fetch_channel_versions;

async fn fetch_version(
    channel: &Channel,
    is_daily: bool,
    update_id: &str,
    server_api: Arc<ServerApi>,
) -> Result<VersionInfo> {
    let versions = fetch_channel_versions(update_id, server_api.clone(), false, is_daily).await?;

    let channel_version = match channel {
        Channel::Stable => versions.stable,
        Channel::Preview => versions.preview,
        Channel::Dev => versions.dev,
        Channel::Integration | Channel::Local | Channel::Oss => {
            // These channels don't ship release artifacts, so there's no
            // version to fetch. This branch is normally unreachable because
            // `AutoupdateState::register` gates the poll loop on the
            // `Autoupdate` feature flag, but builds (e.g. local wasm bundles)
            // can end up with `Autoupdate` enabled while running on one of
            // these channels. Return an error rather than panicking so the
            // poll loop just logs and bails.
            anyhow::bail!(
                "Local, integration, and open-source channel binaries don't support autoupdate"
            );
        }
    };
    let version_info = channel_version.version_info();
    Ok(version_info)
}

fn release_assets_directory_url(channel: Channel, version: &str) -> String {
    let releases_base_url = ChannelState::releases_base_url();
    match channel {
        Channel::Stable => {
            format!("{releases_base_url}/stable/{version}")
        }
        Channel::Preview => {
            format!("{releases_base_url}/preview/{version}")
        }
        Channel::Dev => format!("{releases_base_url}/dev/{version}"),
        Channel::Local | Channel::Integration | Channel::Oss => {
            unreachable!("local/integration/oss autoupdate not supported");
        }
    }
}
"""

WINDOWS_RS = """use anyhow::anyhow;
use anyhow::{bail, Result};
use warp_core::channel::{Channel, ChannelState};

use super::{release_assets_directory_url, DownloadReady};
use crate::util::windows::install_dir;

lazy_static! {
    static ref INSTALLER_PATH: Arc<Mutex<Option<TempPath>>> = Default::default();
}

pub(super) async fn download_update_and_cleanup(
    version_info: &VersionInfo,
    _update_id: &str,
    client: &http_client::Client,
) -> Result<DownloadReady> {
    let installer_file_name = installer_file_name()?;
    Ok(DownloadReady::Yes)
}

fn installer_file_name() -> Result<String> {
    let app_name_prefix = app_name_prefix(ChannelState::channel());

    // For example, on arm64 this is WarpSetup-arm64.exe and on x64 this is
    // WarpSetup.exe.
    if cfg!(target_arch = "aarch64") {
        Ok(format!("{app_name_prefix}Setup-arm64.exe"))
    } else if cfg!(target_arch = "x86_64") {
        Ok(format!("{app_name_prefix}Setup.exe"))
    } else {
        Err(anyhow!(
            "Could not construct setup file name for unsupported architecture"
        ))
    }
}
"""

BUNDLE_PS1 = """} elseif ("$CHANNEL" -eq 'oss') {
    $WARP_BIN = 'warp-oss'
    $FEATURES = 'release_bundle,gui,nld_improvements'
}
"""


class PatchUpdateTests(unittest.TestCase):
    def test_patch_update_rewrites_warp_sources_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root / "app/src/bin/oss.rs", OSS_RS)
            self._write(root / "app/src/autoupdate/mod.rs", AUTOUPDATE_MOD_RS)
            self._write(root / "app/src/autoupdate/windows.rs", WINDOWS_RS)
            self._write(root / "script/windows/bundle.ps1", BUNDLE_PS1)

            changed = run_patch_update(root, "leisure462/warp-globalization", "zh-CN")
            self.assertEqual(len(changed), 4)

            oss = (root / "app/src/bin/oss.rs").read_text(encoding="utf-8")
            self.assertIn("AutoupdateConfig", oss)
            self.assertIn(
                'releases_base_url: "https://github.com/leisure462/warp-globalization/releases/download".into()',
                oss,
            )
            self.assertIn("show_autoupdate_menu_items: true", oss)

            autoupdate_mod = (root / "app/src/autoupdate/mod.rs").read_text(
                encoding="utf-8"
            )
            self.assertIn('const WARP_GLOBALIZATION_GITHUB_REPO: &str = "leisure462/warp-globalization";', autoupdate_mod)
            self.assertIn("fetch_oss_release_version(server_api).await", autoupdate_mod)
            self.assertIn('header("User-Agent", "warp-globalization-updater")', autoupdate_mod)
            self.assertIn('Channel::Oss => format!("{releases_base_url}/{version}")', autoupdate_mod)

            windows = (root / "app/src/autoupdate/windows.rs").read_text(
                encoding="utf-8"
            )
            self.assertIn('const WARP_GLOBALIZATION_RELEASE_LANG: &str = "zh-CN";', windows)
            self.assertIn("installer_file_name(&version_info.version)?", windows)
            self.assertIn('"warp-{}-{platform}-setup-{version}.exe"', windows)

            bundle = (root / "script/windows/bundle.ps1").read_text(encoding="utf-8")
            self.assertIn(
                "$FEATURES = 'release_bundle,gui,nld_improvements,autoupdate,autoupdate_ui_revamp'",
                bundle,
            )

            self.assertEqual(
                run_patch_update(root, "leisure462/warp-globalization", "zh-CN"),
                [],
            )

    def test_patch_update_rejects_unsafe_release_asset_parts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.mkdir(exist_ok=True)

            with self.assertRaises(UpdatePatchError):
                run_patch_update(root, "not a repo", "zh-CN")

            with self.assertRaises(UpdatePatchError):
                run_patch_update(root, "leisure462/warp-globalization", "../zh-CN")

    @staticmethod
    def _write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
