# Track1 Fabric 환경 자동 구성

`deploy_fabric.py`는 Track1 실행에 필요한 Fabric 리소스와 파일을 한 번에 준비합니다. 기본 실행은 읽기 전용 dry run입니다. 실제 변경은 `--apply`를 지정한 경우에만 수행합니다.

## 구성 범위

통합 스크립트는 다음 작업을 순서대로 수행합니다.

1. 대상 Workspace를 ID로 재사용하거나, 이름으로 검색합니다. 이름이 없고 `--create-workspace`를 지정한 경우에는 지정한 Fabric capacity에 새 Workspace를 만듭니다.
2. Workspace 안에서 `IQ_Workshop_Lakehouse`를 찾아 재사용하거나 없으면 생성합니다.
3. 저장소의 CSV 14개를 SHA-256·행 수 기준으로 검증하고 Lakehouse `Files/` 루트에 올립니다.
4. `load_fabric.py`, `standardization.py`, `create_ontology_fabric_v2.py`를 Lakehouse `Files/` 루트에 올립니다. 이 모듈은 원본 적재, 표준 컬럼 생성, Ontology 생성·검증에 사용됩니다.
5. 한국어 Track1 및 Ontology 자동 생성 Notebook을 Workspace에 게시합니다. Notebook 정의의 기본 Lakehouse와 Ontology Notebook의 Workspace/Lakehouse ID를 실제 대상으로 설정합니다.
6. 게시 후 파일 내용과 Notebook 정의를 재검증하고 결과에 Workspace, Lakehouse, 파일 및 Notebook ID를 출력합니다.

`workshop.py`, `deploy_fabric.py`, `run_track1.py`, `upload_fabric_notebooks.py`는 로컬 실행 도구이므로 Lakehouse에는 올리지 않습니다. `create_ontology_fabric_v2.py`라는 새 OneLake 이름을 사용해 기존 런타임 파일을 덮어쓰지 않습니다.

## 사전 조건

- Python 3.10 이상 및 Azure CLI가 설치되어 있어야 합니다.
- `az login`으로 Fabric 접근 권한이 있는 사용자 계정에 로그인합니다.
- 기존 Workspace를 쓸 경우 실행자에게 해당 Workspace Contributor 권한이 필요합니다.
- 새 Workspace를 만들 경우 Fabric 관리자가 Workspace 생성을 허용해야 하며 `--capacity-id`에 지정한 capacity에 대한 권한도 필요합니다. 새 Workspace는 지원되는 Fabric capacity에 할당해야 합니다.
- OneLake 업로드에는 Fabric API용 토큰과 Storage audience 토큰이 필요합니다. 스크립트가 Azure CLI에서 각각 가져오며 토큰 값을 출력하거나 파일에 저장하지 않습니다.
- Ontology Preview 자체의 capacity 및 tenant 설정 조건은 [Ontology 안내](ONTOLOGY_AUTO_CREATE.md#사전-조건)도 확인합니다.

## 실행

먼저 기존 Workspace를 지정해 실제 대상 및 실행 계획을 조회합니다.

```bash
az login
python3 track1/deploy_fabric.py --workspace-id <workspace-id>
```

실제 구성은 계획을 검토한 뒤 `--apply`로 실행합니다.

```bash
python3 track1/deploy_fabric.py --workspace-id <workspace-id> --apply
```

새 Workspace를 만들 때에는 고유한 이름과 Fabric capacity ID를 지정합니다.

```bash
python3 track1/deploy_fabric.py \
  --workspace-name IQ_Workshop_Track1 \
  --create-workspace \
  --capacity-id <capacity-id>
```

위 명령은 dry run입니다. 출력이 맞는지 확인한 뒤 `--apply`를 추가합니다.

```bash
python3 track1/deploy_fabric.py \
  --workspace-name IQ_Workshop_Track1 \
  --create-workspace \
  --capacity-id <capacity-id> \
  --apply
```

`--workspace-name`만 쓰면 같은 이름의 기존 Workspace를 찾고, 없으면 중단합니다. 이름으로 새 Workspace를 만드는 작업은 `--create-workspace`를 명시해야 합니다. `--lakehouse-name`으로 Lakehouse 이름을 바꿀 수 있으며 기본값은 `IQ_Workshop_Lakehouse`입니다.

Notebook만 따로 게시하려면 통합 스크립트 대신 다음 명령을 사용할 수 있습니다. 지정한 Lakehouse ID와 이름이 두 Notebook의 기본값으로 설정됩니다.

```bash
python3 track1/upload_fabric_notebooks.py \
  --workspace-id <workspace-id> \
  --lakehouse-id <lakehouse-id> \
  --lakehouse-name IQ_Workshop_Lakehouse \
  --apply
```

## 안전 동작과 재실행

- 기본 dry run은 Workspace/Lakehouse 목록과 Notebook 목록을 읽고, 로컬 CSV 무결성을 검사하지만 Fabric 리소스나 파일은 변경하지 않습니다.
- Workspace와 Lakehouse는 이름이 일치하면 재사용합니다. 삭제나 교체 작업은 하지 않습니다.
- OneLake에 같은 이름의 파일이 있고 내용까지 같으면 건너뜁니다. 내용이 다르면 덮어쓰지 않고 오류로 중단합니다. 기존 파일이 업로드 중단으로 소스 내용의 정확한 접두부만 가진 경우에는 남은 부분만 이어서 전송합니다.
- 이미 있는 Notebook은 기본적으로 건너뜁니다. 따라서 기존 Notebook이 다른 기본 Lakehouse를 참조하거나 오래된 코드라면 그대로 유지됩니다. 저장소의 Notebook definition과 새 기본 Lakehouse 연결로 교체하려면 `--update-existing-notebooks --apply`를 함께 지정하세요. 이 옵션은 Notebook definition 전체를 교체합니다.
- 중간 실패 시 이미 생성한 Workspace/Lakehouse나 업로드한 파일은 자동 삭제하지 않습니다. 오류를 확인한 뒤 같은 명령을 재실행하면 동일한 리소스와 파일을 재사용합니다.

## 전체 Track1 자동 실행

아래 명령은 Notebook과 런타임 파일을 배포·갱신하고 Fabric on-demand Notebook job API로 전체 파이프라인을 실행한 뒤 완료까지 대기합니다.

```bash
python3 track1/run_track1.py \
  --workspace-id <workspace-id> \
  --apply
```

실행은 원본 CSV의 해시/행 수를 검증하고, 기존 `workshop_` 테이블을 보존하면서 Q1~Q5를 실행합니다. 성공하면 변환 규칙을 적용한 새 `_ontology_v4` backing 테이블을 추가하고 `IQ_Workshop_Track1_Ontology` 전체 정의를 저장소 정의로 갱신합니다. Decimal 표준 컬럼은 Ontology 속성과 정밀도/소수점 자릿수를 맞추도록 `decimal(38,6)`으로 저장합니다. 따라서 Ontology에 수동으로 추가한 정의가 있다면 먼저 백업하세요. 기존 원본 테이블과 이전 `_ontology` 테이블은 덮어쓰거나 삭제하지 않습니다. 자동 실행은 OneLake의 두 명시적 런타임 파일(`standardization.py`, `create_ontology_fabric_v2.py`)과 해당 Notebook 정의만 갱신합니다. `--apply`가 없으면 dry-run만 수행합니다. 실행 계정에는 Notebook 실행과 대상 Workspace/Lakehouse 및 Ontology 쓰기 권한이 필요합니다.

`--lakehouse-id <lakehouse-id>`를 추가하면 지정한 이름의 Lakehouse가 해당 ID와 일치하지 않을 때 파일 업로드나 Notebook 교체 전에 중단합니다. 마지막 단계는 연결된 GraphModel을 구성·refresh하고 그래프 타입과 두 GQL 스모크 쿼리를 확인합니다. 이미 구성된 그래프를 변경 없이 검사하려면 [읽기 전용 검증 명령](README.md#complete-track1-automatically)을 사용하세요.

## 구성 스크립트

| 스크립트 | 목적 |
| --- | --- |
| `workshop.py` | 로컬 원본 CSV 다운로드, 검증, Q1~Q5 분석 |
| `deploy_fabric.py` | Workspace/Lakehouse 확인·생성 및 CSV·Track1 Python 파일·Notebook 게시 |
| `run_track1.py` | 배포, Notebook 실행, GraphModel 구성·refresh·검증 |
| `materialize_graph.py` | GraphModel 구성·refresh 또는 변경 없는 기존 그래프 검증 |
| `upload_fabric_notebooks.py` | Notebook만 따로 게시할 때 사용하는 보조 배포 도구 |
| `load_fabric.py` | Fabric Spark Notebook에서 원본 CSV를 검증해 Delta 테이블로 적재 |
| `standardization.py` | 원본→표준 컬럼 변환과 데이터형 규칙 |
| `create_ontology_fabric.py` | Fabric Spark Notebook에서 Ontology 모델을 생성·검증 |

전체 테스트 및 기본 검증:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile track1/deploy_fabric.py track1/upload_fabric_notebooks.py
```

## 공식 참고

- [Create Workspace REST API](https://learn.microsoft.com/en-us/rest/api/fabric/core/workspaces/create-workspace)
- [Create Lakehouse REST API](https://learn.microsoft.com/en-us/rest/api/fabric/lakehouse/items/create-lakehouse)
- [OneLake REST API 및 파일 업로드](https://learn.microsoft.com/en-us/fabric/onelake/onelake-access-api)
- [Notebook definition](https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/notebook-definition)
