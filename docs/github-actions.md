# GitHub Actions 설정 최종 안내

[프로젝트 소개](../README.md) · [컨테이너 빌드·배포](containers.md)

## 실행 흐름

작업 브랜치에서 `main`으로 PR을 만들고, 검사 통과 후 머지합니다. 원하는 출시 시점에 `main`의 커밋에 버전 태그를 만들어 푸시합니다.

| 시점 | 실행 |
| --- | --- |
| 작업 브랜치 푸시, PR 없음 | 실행 없음 |
| main 대상 PR 생성·갱신·재오픈 | 품질·보안·앱·브라우저 검사 병렬 실행 |
| main 머지·푸시 | 추가 실행 없음; GHCR 이미지도 게시하지 않음 |
| 버전 태그 푸시 | main 포함 여부·전체 검사 → 검증용 이미지 업로드 → 기동·취약점 검사 → 정식 이미지 태그·릴리즈 게시 |
| main·작업 브랜치에서 Run workflow | 검증만 실행 |
| 버전 태그에서 Run workflow | 해당 태그의 출시 과정 재실행 |

별도 보안 워크플로는 주 1회 예약 검사도 수행합니다. PR을 연 뒤 추가 푸시하면 변경된 코드를 검사하기 위해 해당 PR 검사를 다시 실행합니다.

## 1. Actions 활성화와 권한

저장소 **Settings → Actions → General**에서 설정합니다.

- **Actions permissions:** Actions를 활성화합니다. 제한 목록을 사용한다면 `actions/*`, `docker/*`, `github/codeql-action/*`를 허용하세요. **Allow all actions and reusable workflows**를 선택해도 현재 워크플로를 실행할 수 있습니다.
- **Workflow permissions:** 기본값은 **Read repository contents and packages permissions**로 유지할 수 있습니다. YAML에서 이미지 게시·정식 태그 확정 작업만 `packages: write`, 릴리즈 생성만 `contents: write`를 요청합니다.
- **Allow GitHub Actions to create and approve pull requests:** 이 프로젝트에는 필요하지 않습니다.

별도의 PAT·Docker Hub 로그인·서버 접속 키·운영 DB/S3 비밀값을 Actions Secrets에 추가할 필요가 없습니다. 기본 `GITHUB_TOKEN`과 검사 때마다 생성하는 임시 키를 사용합니다.

[GitHub Actions 설정](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository) · [토큰 권한 계산](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#how-permissions-are-calculated-for-a-workflow-job)

## 2. main 보호 규칙

현재 브랜치로 PR을 한 번 실행해 체크 이름이 등록된 후, **Settings → Rules → Rulesets**에서 기존 `main` 규칙을 편집하거나 **New branch ruleset**을 만듭니다. 같은 브랜치에 적용되는 기존 규칙이 있으면 함께 적용되므로 기존 규칙도 확인하세요.

| 항목 | 값 |
| --- | --- |
| Ruleset name | Protect main |
| Enforcement status | Active |
| Target branches | main (`refs/heads/main`) |
| Bypass list | 비워두기 |
| Require a pull request before merging | 켜기 |
| Required approvals | 혼자 작업하면 0명 |
| Require status checks to pass | 켜기, 아래 11개 추가 |
| Require branches to be up to date before merging | 켜기 |
| Block force pushes | 켜기 |
| Restrict deletions | 켜기 |

필수 검사에는 PR에서 실행되는 다음 작업만 지정합니다. 검사 출처를 고를 수 있으면 **GitHub Actions**를 선택하세요.

```text
Code quality / Python lint
Code quality / Vue and JavaScript lint
Code quality / GitHub Actions lint
Dependency and security analysis / Python lock and vulnerability audit
Dependency and security analysis / npm vulnerability audit
Dependency and security analysis / CodeQL (python)
Dependency and security analysis / CodeQL (javascript-typescript)
Checks / Source and deployment configuration
Checks / Frontend tests and image build
Checks / Backend tests
Browser tests / Chromium with PostgreSQL and Garage
```

`Validate release tag`, `Publish images`, `Verify release images`, `Create release`는 태그 실행용이므로 PR 필수 체크에 넣지 마세요. PR 목록에 체크가 아직 없으면 현재 변경을 푸시하고 `main` 대상 PR에서 한 번 실행한 뒤 추가하세요. 재사용 워크플로 체크 이름은 `호출 작업 이름 / 내부 작업 이름` 형식입니다.

`main`으로 머지하는 PR의 출처를 특정 브랜치로 제한할 필요는 없습니다. 작업 브랜치는 머지 후 삭제해도 됩니다. 기존에 `dev`를 만들었더라도 이 워크플로는 `dev`를 요구하지 않습니다.

[Ruleset 생성](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository) · [체크 이름 형식](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/troubleshooting-rules)

## 3. GHCR 패키지 설정

버전 태그 실행이 처음 검증용 이미지를 업로드하면 사용자 프로필의 **Packages**에 다음 두 패키지가 생깁니다.

- `catppuccindock-frontend`
- `catppuccindock-backend`

각 패키지의 **Package settings**에서 설정합니다.

1. 패키지가 `overture-1928/CatppuccinDock` 저장소에 연결됐는지 확인합니다.
2. **Manage Actions access**에서 이 저장소가 이미지를 읽고 쓸 수 있어야 합니다. 상속되지 않은 기존 패키지라면 저장소를 추가하고 **Write** 권한을 부여합니다.
3. 서버에서 로그인 없이 설치하려면 **Change visibility → Public**으로 변경합니다. 저장소 공개 여부와 패키지 공개 여부는 별개입니다.

첫 업로드 전에는 이 패키지 설정 화면이 없을 수 있습니다. 출시 검사는 기본 토큰으로 비공개 패키지도 읽을 수 있으므로 Public 변경을 기다릴 필요는 없습니다. Public 변경은 서버에서 익명으로 내려받기 위한 설정입니다.

[Container Registry 권한 안내](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)

## 4. 출시하기

먼저 이 워크플로 변경을 `main`에 머지합니다. 출시할 변경들도 PR로 머지한 뒤 아래 명령을 실행하세요. `v1.0.6`은 아직 사용하지 않은 버전으로 바꿉니다.

```bash
git fetch origin
git tag -a v1.0.6 origin/main -m "Release v1.0.6"
git push origin refs/tags/v1.0.6
```

이 명령은 현재 작업 브랜치와 관계없이 최신 원격 `main` 커밋에 태그를 만듭니다. 태그 생성만으로는 Actions가 시작되지 않으며, 마지막 푸시가 필요합니다. `main`을 직접 푸시할 필요는 없습니다.

`v1.0.6` 같은 정식 버전은 모든 출시 검사 통과 후 `1.0.6`, `1.0`, `sha-커밋`, `latest` 이미지 태그를 게시합니다. `v1.1.0-rc.1` 같은 사전 릴리즈는 `latest`를 바꾸지 않고 GitHub에서도 Prerelease로 표시합니다. `IMAGE_TAG=latest` 운영 서버는 새 정식 버전을 내려받고, `IMAGE_TAG=1.0.6`으로 고정한 서버는 해당 버전을 유지합니다.

태그 규칙을 별도로 추가한다면 기존 버전 태그의 변경·삭제를 막는 용도로 사용할 수 있습니다. 출시 검사는 태그가 푸시된 뒤 실행되므로 PR 필수 체크 11개를 태그 생성 조건으로 추가하지 마세요.

## 5. 실패했을 때

- 태그 대상 검사 실패: `main`에 포함되지 않은 커밋이거나 버전 형식이 잘못됐는지 확인합니다.
- 기동 검사 실패: 게시한 이미지로 프론트·DB·S3 연결이 정상인지 확인합니다. 각 테스트는 임시 프로젝트와 볼륨을 사용합니다.
- 취약점 검사 실패: Actions 로그에 표시된 수정 가능 패키지를 갱신하고, `release-image-scan-amd64`·`release-image-scan-arm64` Artifacts에서 전체 JSON 보고서를 받습니다. 공급처가 수정 버전을 제공한 HIGH·CRITICAL과 예외가 없는 모든 CRITICAL 항목을 차단합니다. 수정 버전이 없는 Critical의 임시 예외는 `.github/trivy-release-ignore.yaml`에 사유와 만료일을 기록하며, 수정 버전이 나오거나 예외가 만료되면 다시 차단합니다. 나머지 미수정 항목도 보고서에 남겨 14일 보관합니다.
- 검사 실패 시 `candidate-*` 이미지는 남을 수 있지만 정식 이미지 태그와 GitHub 릴리즈는 게시하지 않습니다. 버그 수정은 새 PR·새 버전으로 출시하고, 일시적 네트워크 실패는 **Re-run failed jobs**로 재시도합니다.
- 14일이 지나 이미지 기록 Artifacts가 만료됐다면 전체 태그 워크플로를 재실행해 빌드 기록부터 다시 만드세요.
- 실제 서버의 `docker compose pull`·`docker compose up -d`는 별도 배포 작업입니다. 이 워크플로가 서버에 접속하지는 않습니다.
