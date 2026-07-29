# Intellectual-property and publication governance

This document is an operational checklist, not a substitute for advice from
the authors' institution or qualified counsel.

## What the repository protects

Copyright arises automatically in original, fixed human-authored expression in
software, prose, and visual works. The repository's commit history,
provenance manifests, checksums, releases, and citation metadata help identify
what existed at a particular version and who publicly claimed responsibility
for it.

The repository now separates four questions:

1. **Software permission:** MIT permits broad reuse of code while requiring
   preservation of the copyright and permission notice.
2. **Research-material permission:** CC BY-NC-ND 4.0 requires attribution,
   limits covered prose and figures to noncommercial sharing, and prohibits
   distribution of adaptations without permission.
3. **Evidence reuse:** CC BY 4.0 permits independent analysis of covered data
   while requiring attribution.
4. **Scholarly credit:** `CITATION.cff` tells researchers how to cite the
   software. Citation is not a substitute for license compliance, and a
   software license cannot by itself enforce the authorship rules of a
   conference or journal.

The exact mapping is in [`LICENSE_SCOPE.md`](../LICENSE_SCOPE.md).

## What it does not protect

Copyright does not protect scientific facts, discoveries, algorithms, ideas,
procedures, systems, or methods of operation; it protects their original
expression. A public GitHub repository is also a disclosure, not a
confidentiality mechanism. If a potentially patentable invention exists,
institutional technology-transfer or patent counsel should review it before
further public disclosure.

The repository cannot establish that an individual owns work created within
employment, university, funded-project, collaboration, or commissioned-work
obligations. Each human author must check those agreements. It also cannot
license NVIDIA, Isaac Lab, Unitree, publisher, or other third-party rights.

For AI-assisted material, preserve records of the human choices, revisions,
experimental design, code review, and arrangement that constitute human
authorship. In the United States, appreciable AI-generated material must be
disclosed in a copyright-registration application, and prompting alone may
not establish copyrightable authorship.

## Publication checklist

Before preprint or ICRA/IEEE submission:

- confirm legal names, affiliations, contribution statements, author order,
  employer/university ownership, funding terms, and corresponding-author
  authority in writing;
- tag the exact submitted code and evidence, archive that tag with an
  independent preservation service such as Zenodo, and add the resulting DOI
  to `CITATION.cff`;
- preserve the source manuscript, figures, raw-to-result manifests, and
  checksums; do not rewrite or delete negative evidence;
- verify permissions for third-party figures, robot images, policies,
  checkpoints, datasets, and trademarks;
- evaluate patentability before any additional public technical disclosure;
- record which manuscript and figure elements involved AI assistance and the
  human authorship contributed to them.

After IEEE acceptance:

- read the actual publishing agreement before signing it;
- update `CITATION.cff` with the paper DOI and preferred citation;
- replace preprint references as required by the agreement;
- post only versions and notices the agreement permits;
- do not upload the IEEE Xplore version of record unless the chosen
  open-access license or written permission allows it;
- add a file-specific copyright notice to the accepted manuscript so the
  repository's general Creative Commons notice is not mistaken for permission
  to reuse IEEE-owned material.

## If misuse is suspected

1. Preserve the allegedly copied work, URL, date, screenshots, repository
   commit, release archive, and checksums.
2. Compare protectable expression rather than only the shared scientific idea
   or result.
3. Identify which license and version applied and whether attribution,
   commercial-use, or no-derivatives terms were breached.
4. Use the relevant institution, publisher, conference ethics process, host
   notice process, or qualified counsel. Do not alter historical evidence
   while a dispute is being assessed.

## Authoritative references

- [WIPO: copyright protection is automatic and protects expression, not ideas](https://www.wipo.int/en/web/copyright/protection)
- [GitHub: licensing a repository and the effect of having no license](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
- [Creative Commons BY-NC-ND 4.0 legal code](https://creativecommons.org/licenses/by-nc-nd/4.0/legalcode.en)
- [Creative Commons BY 4.0 legal code](https://creativecommons.org/licenses/by/4.0/legalcode.en)
- [U.S. Copyright Office: copyright and AI, Part 2](https://www.copyright.gov/ai/Copyright-and-Artificial-Intelligence-Part-2-Copyrightability-Report.pdf)
- [IEEE: choosing a publishing agreement](https://journals.ieeeauthorcenter.ieee.org/choose-a-publishing-agreement/)
- [IEEE: posting an accepted conference paper](https://support.ieeemce.org/hc/en-us/articles/28339511410971-Can-I-publish-my-accepted-paper-on-my-personal-website-or-in-my-institutional-database)

## 中文执行摘要

当前治理采用分层许可：代码为 MIT；原创科研文稿和图片为
CC BY-NC-ND 4.0；原创机器可读证据数据为 CC BY 4.0；第三方资产不在
CalibAgent 的授权范围内。`CITATION.cff` 提供 GitHub 可识别的标准引用。

这能够改善复制、改编、商业使用、署名和数据再分析的边界，但不能靠版权
保护算法思想、事实或实验方法，也不能替代专利、出版协议和学术伦理程序。
公开 GitHub 仓库已经构成技术披露；若存在潜在专利，应在继续公开前联系
学校技术转移部门或专利律师。

在 ICRA/IEEE 接收后，必须以实际签署的出版协议为准。除非开放获取许可或
书面许可明确允许，不得把 IEEE Xplore 的最终版本 PDF 当作本仓库
CC 许可材料上传。应当给可公开的作者版本添加 IEEE 要求的声明，并把论文
DOI 更新到 `CITATION.cff`。

对于 AI 辅助生成的代码、文字或图片，应保存人的实验设计、筛选、修改、
组合和审核记录。版权声明只覆盖权利人实际拥有且符合法律保护条件的部分。
