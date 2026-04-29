from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class UpdatePatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdatePatchConfig:
    source_root: Path
    repo: str
    lang: str


_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ASSET_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def run_patch_update(source_root: str | Path, repo: str, lang: str) -> list[Path]:
    config = UpdatePatchConfig(Path(source_root), repo, lang)
    _validate_config(config)

    changed: list[Path] = []
    for patcher in (
        _patch_oss_entry,
        _patch_autoupdate_mod,
        _patch_windows_updater,
        _patch_windows_bundle,
    ):
        changed.extend(patcher(config))
    return changed


def _validate_config(config: UpdatePatchConfig) -> None:
    if not config.source_root.exists():
        raise UpdatePatchError(f"source root does not exist: {config.source_root}")
    if not _REPO_RE.fullmatch(config.repo):
        raise UpdatePatchError(f"GitHub repo must look like owner/name: {config.repo}")
    if not _ASSET_PART_RE.fullmatch(config.lang):
        raise UpdatePatchError(f"language is not safe for release asset names: {config.lang}")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _replace_once(path: Path, old: str, new: str, description: str) -> bool:
    text = _read(path)
    if new in text:
        return False
    if old in text:
        _write(path, text.replace(old, new, 1))
        return True

    old_crlf = old.replace("\n", "\r\n")
    if old_crlf in text:
        _write(path, text.replace(old_crlf, new.replace("\n", "\r\n"), 1))
        return True

    raise UpdatePatchError(
        f"{path}: could not find expected {description}; upstream source may have changed"
    )


def _patch_oss_entry(config: UpdatePatchConfig) -> list[Path]:
    path = config.source_root / "app/src/bin/oss.rs"
    changed = False

    changed |= _replace_once(
        path,
        """use warp_core::{
    channel::{Channel, ChannelConfig, ChannelState, OzConfig, WarpServerConfig},
    AppId,
};
""",
        """use warp_core::{
    channel::{
        AutoupdateConfig, Channel, ChannelConfig, ChannelState, OzConfig, WarpServerConfig,
    },
    AppId,
};
""",
        "OSS channel import block",
    )

    changed |= _replace_once(
        path,
        """            telemetry_config: None,
            crash_reporting_config: None,
            autoupdate_config: None,
            mcp_static_config: None,
""",
        f"""            telemetry_config: None,
            crash_reporting_config: None,
            autoupdate_config: Some(AutoupdateConfig {{
                releases_base_url: "https://github.com/{config.repo}/releases/download".into(),
                show_autoupdate_menu_items: true,
            }}),
            mcp_static_config: None,
""",
        "OSS autoupdate config",
    )

    return [path] if changed else []


def _patch_autoupdate_mod(config: UpdatePatchConfig) -> list[Path]:
    path = config.source_root / "app/src/autoupdate/mod.rs"
    changed = False

    changed |= _replace_once(
        path,
        "use rand::Rng as _;\n",
        "use rand::Rng as _;\nuse serde::Deserialize;\n",
        "serde import",
    )

    changed |= _replace_once(
        path,
        "use self::channel_versions::fetch_channel_versions;\n",
        f"""use self::channel_versions::fetch_channel_versions;

const WARP_GLOBALIZATION_GITHUB_REPO: &str = "{config.repo}";
const GITHUB_LATEST_RELEASE_TIMEOUT_SECS: u64 = 30;

#[derive(Debug, Deserialize)]
struct GithubRelease {{
    tag_name: String,
}}
""",
        "GitHub release metadata definitions",
    )

    changed |= _replace_once(
        path,
        """async fn fetch_version(
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
""",
        """async fn fetch_version(
    channel: &Channel,
    is_daily: bool,
    update_id: &str,
    server_api: Arc<ServerApi>,
) -> Result<VersionInfo> {
    if matches!(channel, Channel::Oss) {
        return fetch_oss_release_version(server_api).await;
    }

    let versions = fetch_channel_versions(update_id, server_api.clone(), false, is_daily).await?;

    let channel_version = match channel {
        Channel::Stable => versions.stable,
        Channel::Preview => versions.preview,
        Channel::Dev => versions.dev,
        Channel::Integration | Channel::Local => {
            // These channels don't ship release artifacts, so there's no
            // version to fetch. This branch is normally unreachable because
            // `AutoupdateState::register` gates the poll loop on the
            // `Autoupdate` feature flag, but builds (e.g. local wasm bundles)
            // can end up with `Autoupdate` enabled while running on one of
            // these channels. Return an error rather than panicking so the
            // poll loop just logs and bails.
            anyhow::bail!("Local and integration channel binaries don't support autoupdate");
        }
        Channel::Oss => unreachable!("open-source channel version is fetched from GitHub Releases"),
    };
    let version_info = channel_version.version_info();
    Ok(version_info)
}

async fn fetch_oss_release_version(server_api: Arc<ServerApi>) -> Result<VersionInfo> {
    let url = format!(
        "https://api.github.com/repos/{WARP_GLOBALIZATION_GITHUB_REPO}/releases/latest"
    );
    log::info!("Fetching latest Warp globalization release from {url}");

    let release: GithubRelease = server_api
        .http_client()
        .get(url.as_str())
        .header("Accept", "application/vnd.github+json")
        .header("User-Agent", "warp-globalization-updater")
        .header("X-GitHub-Api-Version", "2022-11-28")
        .timeout(Duration::from_secs(GITHUB_LATEST_RELEASE_TIMEOUT_SECS))
        .send()
        .await
        .context("Failed to retrieve latest Warp globalization release from GitHub")?
        .error_for_status()
        .context("GitHub latest release request failed")?
        .json()
        .await
        .context("Failed to parse GitHub latest release response")?;

    let version = release.tag_name.trim();
    if version.is_empty() {
        anyhow::bail!("GitHub latest release response did not include tag_name");
    }

    Ok(VersionInfo::new(version.to_owned()))
}
""",
        "fetch_version implementation",
    )

    changed |= _replace_once(
        path,
        """fn release_assets_directory_url(channel: Channel, version: &str) -> String {
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
""",
        """fn release_assets_directory_url(channel: Channel, version: &str) -> String {
    let releases_base_url = ChannelState::releases_base_url();
    match channel {
        Channel::Stable => {
            format!("{releases_base_url}/stable/{version}")
        }
        Channel::Preview => {
            format!("{releases_base_url}/preview/{version}")
        }
        Channel::Dev => format!("{releases_base_url}/dev/{version}"),
        Channel::Oss => format!("{releases_base_url}/{version}"),
        Channel::Local | Channel::Integration => {
            unreachable!("local/integration autoupdate not supported");
        }
    }
}
""",
        "release asset URL builder",
    )

    return [path] if changed else []


def _patch_windows_updater(config: UpdatePatchConfig) -> list[Path]:
    path = config.source_root / "app/src/autoupdate/windows.rs"
    changed = False

    changed |= _replace_once(
        path,
        "use crate::util::windows::install_dir;\n\nlazy_static!",
        f"""use crate::util::windows::install_dir;

const WARP_GLOBALIZATION_RELEASE_LANG: &str = "{config.lang}";

lazy_static!""",
        "Windows updater release language constant",
    )

    changed |= _replace_once(
        path,
        "    let installer_file_name = installer_file_name()?;\n",
        "    let installer_file_name = installer_file_name(&version_info.version)?;\n",
        "Windows installer filename call",
    )

    changed |= _replace_once(
        path,
        """fn installer_file_name() -> Result<String> {
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
""",
        """fn installer_file_name(version: &str) -> Result<String> {
    if matches!(ChannelState::channel(), Channel::Oss) {
        let platform = if cfg!(target_arch = "aarch64") {
            "windows-aarch64"
        } else if cfg!(target_arch = "x86_64") {
            "windows-x86_64"
        } else {
            return Err(anyhow!(
                "Could not construct setup file name for unsupported architecture"
            ));
        };

        return Ok(format!(
            "warp-{}-{platform}-setup-{version}.exe",
            WARP_GLOBALIZATION_RELEASE_LANG
        ));
    }

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
""",
        "Windows installer filename builder",
    )

    return [path] if changed else []


def _patch_windows_bundle(config: UpdatePatchConfig) -> list[Path]:
    path = config.source_root / "script/windows/bundle.ps1"
    changed = _replace_once(
        path,
        "    $FEATURES = 'release_bundle,gui,nld_improvements'\n",
        "    $FEATURES = 'release_bundle,gui,nld_improvements,autoupdate,autoupdate_ui_revamp'\n",
        "Windows OSS bundle feature set",
    )
    return [path] if changed else []
