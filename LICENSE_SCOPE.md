# CalibAgent license scope

Copyright © 2026 EurekaZang and CalibAgent contributors.

This file defines the licensing boundary for repository versions that contain
it. It does not revoke or narrow permissions validly granted for an earlier
version of any file. A file-specific notice takes precedence over this
repository-level declaration.

## License matrix

| Material | Repository scope | License |
|---|---|---|
| Software | `src/`, `sim/`, `scripts/`, `tests/`, `configs/`, `env/`, `.github/`, `pyproject.toml`, `uv.lock`, and source or shell files under `data/calibration_extracted/` | [MIT](LICENSE) |
| Research prose and visual material | `README.md`, `README_zh-CN.md`, Markdown and authored visual material under `docs/`, Markdown/PDF/PNG material under `reports/` and `evidence/`, and the root engineering-plan DOCX | [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/legalcode.en) |
| Research data and evidence records | Machine-readable CSV, JSON, YAML, Parquet, NPZ, compressed trace, checksum, and manifest files under `evidence/` and `reports/`, plus JSON provenance under `docs/assets/` | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode.en) |
| Untracked or ignored material | Local `data/`, `outputs/`, credentials, private robot recordings, and any material not actually committed | No license is granted by this repository |
| Third-party material | External runtimes, policies, robot/simulator assets, trademarks, and any file carrying its own notice | The applicable third-party terms |

The Creative Commons grants apply only to copyright, database rights, and
similar rights that the licensors actually hold. They do not create ownership
over individual facts, public-domain material, or third-party content.
Underlying NVIDIA Isaac Sim/Isaac Lab and Unitree assets, policies, names, and
marks are not relicensed here. For simulator images, the applicable grant is
limited to CalibAgent's original selection, composition, annotations, and
other protectable contributions.

## Required attribution

When a Creative Commons license applies, use at least:

> CalibAgent, EurekaZang and CalibAgent contributors, version or commit used,
> https://github.com/EurekaZang/CalibAgent, under the applicable license.

Also retain the copyright notice, link the applicable license, identify the
specific material, and indicate changes when the license permits changes.
The exact software citation is machine-readable in
[`CITATION.cff`](CITATION.cff). Academic citation and legal license attribution
serve different purposes; researchers should provide both when both apply.

## Boundaries

- The MIT software license permits commercial use, modification,
  redistribution, sublicensing, and sale subject to retention of its notice.
  It does not require citation of a paper.
- CC BY-NC-ND 4.0 permits sharing the covered research prose and visual
  material with attribution for noncommercial purposes, but does not permit
  sharing adaptations without separate permission.
- CC BY 4.0 permits reuse and adaptation of the covered research data with
  attribution, supporting independent analysis and reproducibility.
- No trademark license, endorsement, or right to use the CalibAgent name as
  the name of a derived project is granted.
- Copyright does not protect the underlying ideas, scientific facts,
  algorithms, procedures, or methods. No separate patent license is granted
  for research materials by the Creative Commons licenses.
- A future submitted, accepted, or published manuscript is governed by its
  file-specific notice and the applicable publisher agreement. A repository
  license must not be assumed to authorize reuse of an IEEE version of record.

## Ownership and prior versions

Only a person or entity that owns the relevant rights can license them.
Employer, university, sponsor, coauthor, privacy, publicity, and third-party
contract rights can override an individual's assumption of ownership. The
project maintainer must verify those rights before adding a manuscript,
external dataset, robot recording, model checkpoint, or third-party figure.

Earlier commits distributed under the MIT notice remain available under the
permissions attached to those versions. The more specific scope above governs
new repository versions containing this declaration; it is not a retroactive
withdrawal of an irrevocable prior grant.

## 中文说明

本文件对仓库进行分层许可：

- 软件代码继续使用 MIT，以维持复现与二次开发能力；
- 原创科研文稿、报告和图片采用 CC BY-NC-ND 4.0，要求署名、限制商业
  使用，并禁止未经许可传播改编版本；
- 原创机器可读实验数据采用 CC BY 4.0，允许复核和再分析，但必须署名；
- NVIDIA Isaac Sim/Isaac Lab、Unitree 资产、策略、名称和商标仍由其各自
  权利人管理，本仓库不对其重新授权；
- 旧提交中已经生效的 MIT 授权不能被追溯撤销；
- 版权保护具体表达，不保护算法思想、科学事实和实验方法本身。

若中英文解释出现歧义，以适用许可证的正式法律文本和本文件英文范围说明为准。
