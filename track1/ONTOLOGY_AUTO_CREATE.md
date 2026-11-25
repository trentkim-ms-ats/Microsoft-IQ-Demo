# Track1 Ontology 자동 생성 안내 (Preview)

이 안내와 `create_ontology_fabric.py`는 원본 워크숍의 CSV 14개를 사용해 Fabric의 generation-2 Ontology를 REST API로 생성하는 재사용 절차입니다. `IQ_Workshop_Ontology_AutoCreate.ipynb`는 Fabric에서 스크립트를 실행하는 설정 Notebook입니다. Fabric Ontology 및 일부 API는 Preview이므로 API 형식과 기능이 변경될 수 있습니다.

`model.tmdl`의 `ref namespace`, `ref table`, `ref entity` 선언은 TMDL 문서의 최상위 참조 항목으로 생성하며 `model Model` 아래에 들여쓰지 않습니다. 들여쓰면 Fabric 파서가 참조를 `model` 객체의 유효하지 않은 내부 항목으로 해석해 `Unexpected line type: ReferenceObject` 오류를 반환합니다.

## 생성되는 모델

각 원본 CSV를 `workshop_{파일명}` Delta 테이블로 적재한 상태를 전제로 합니다. 생성기는 아래 14개 엔터티와 데이터 열, 18개 관계를 TMDL 정의에 포함합니다.

| 원본 CSV | Ontology 엔터티 | 식별자 |
| --- | --- | --- |
| `channels.csv` | Channel | `channel_id` |
| `customers.csv` | Customer | `customer_id` |
| `products.csv` | Product | `product_id` |
| `campaigns.csv` | Campaign | `campaign_id` |
| `promotions.csv` | Promotion | `promotion_id` |
| `orders.csv` | Order | `order_id` |
| `order_items.csv` | OrderItem | 합성 `ontology_entity_id` |
| `payments.csv` | Payment | `payment_id` |
| `shipments.csv` | Shipment | 합성 `ontology_entity_id` |
| `returns.csv` | Return | `return_id` |
| `inventory_snapshots.csv` | InventorySnapshot | `snapshot_id` |
| `order_promotions.csv` | OrderPromotion | 합성 `ontology_entity_id` |
| `campaign_attribution.csv` | CampaignAttribution | 합성 `ontology_entity_id` |
| `support_tickets.csv` | SupportTicket | `ticket_id` |

`channels` 외 엔터티는 타입 변환 또는 합성 키를 포함하는 `workshop_{파일명}_ontology_v4` backing 테이블을 사용합니다. 표준화 대상 원본 컬럼은 `<원본 컬럼>_raw`로 보존하고, 별도 typed `*_std` 컬럼을 추가합니다. Decimal 속성은 Ontology의 `DECIMAL(38,6)` 정의와 일치하도록 Delta `decimal(38,6)`으로 저장합니다. `order_items`, `shipments`, `order_promotions`, `campaign_attribution`에는 원본 모든 열의 SHA-256 지문과 동일 행 순번으로 만든 합성 키도 추가합니다. Ontology의 14개 테이블은 SQL analytics endpoint가 아니라 `AzureStorage.DataLake` OneLake 연결식과 Lakehouse Delta 테이블의 `entityName`을 사용해 직접 바인딩합니다. 원본 CSV, `workshop_` 원본 테이블, 이전 `_ontology` backing 테이블은 변경하지 않습니다. v4 테이블이 이미 있으면 원본에서 다시 계산한 전체 행과 비교하며, 차이가 있으면 덮어쓰지 않고 중단합니다.

표준화 규칙은 `standardization.py`에 한 곳에서 정의합니다. 상태는 `Completed → PAID`, `RetrySuccess → AUTHORIZED`, `InTransit → IN_TRANSIT`으로 정규화하며, `SupportTicket.reason`은 기존 사유를 의미 손실 없이 `UPPER_SNAKE_CASE`로 바꿉니다. 날짜/시각, 금액, 수량도 각각 date/timestamp, decimal, integer backing 컬럼으로 변환합니다. 누락된 매핑 값이나 실패한 타입 변환은 자동 통과시키지 않고 실행을 중단합니다.

원본 샘플의 데이터 품질도 함께 확인합니다. 현재 고정 샘플에서는 `order_items`의 `(order_id, product_id)` 조합이 3행에서 중복되고 `shipments.shipment_id`가 1행에서 중복됩니다. 또한 `payments.order_id`와 `support_tickets.customer_id`에는 각 1개의 고아 참조가 있습니다. 생성기는 이런 행을 제거하거나 수정하지 않습니다. API에 전달하기 전에 모든 원본 행 수·열·키를 검증하고, 관계의 결측/고아 참조 수를 결과에 표시합니다.

## 사전 조건

1. Ontology Preview가 지원되는 Fabric 용량의 Workspace를 준비하고, 실행 계정에 해당 Workspace의 **Contributor** 권한을 부여합니다.
2. 테넌트 설정 **Users can create ontology (preview) items**와 **Users can create Fabric items**를 켭니다. 이 설정은 Fabric 관리자가 **OneLake catalog → Govern → Configurations → Tenant settings**에서 확인합니다.
3. Workspace에 `IQ_Workshop_Lakehouse`와 `workshop_` 접두사의 14개 원본 Delta 테이블을 준비합니다. 생성 Notebook에는 해당 Lakehouse를 기본 Lakehouse로 연결합니다.
5. Fabric REST API 호출에 실행 사용자의 권한이 필요합니다. Notebook은 `notebookutils.credentials.getToken("pbi")`를 사용하고 토큰을 출력하거나 파일에 저장하지 않습니다.

## Fabric에서 실행

전체 절차는 [Track1 자동 실행 안내](README.md#complete-track1-automatically)의 `python3 track1/run_track1.py ... --apply` 명령으로 실행할 수 있습니다. 이 명령은 Notebook과 버전된 런타임 모듈을 게시하고, Fabric job API로 `IQ_Workshop_Track1_KO`를 실행합니다. Notebook은 원본·Q1~Q5를 검증한 다음 표준화 backing 테이블과 OneLake 직접 바인딩 Ontology를 생성·갱신하고, API `getDefinition`을 읽어 Lakehouse binding 14개와 표준 속성 27개를 확인합니다. 마지막으로 연결된 GraphModel 정의를 REST API로 구성하고 materialize job을 실행한 뒤, queryable graph type과 노드/관계 쿼리를 검증합니다.

`IQ_Workshop_Ontology_AutoCreate`는 별도 진단용 Notebook으로 남아 있으며 기본값은 dry-run입니다. 이를 수동 실행할 때에는 기존 동작처럼 `APPLY`와 `UPDATE_EXISTING`을 의도에 맞게 설정하세요.

같은 이름의 Ontology가 이미 있으면 기본적으로 생성을 거부합니다. 기존 정의를 교체할 의도가 분명할 때만 `UPDATE_EXISTING = True`를 설정하세요. 업데이트 API는 Ontology의 **전체 definition을 덮어씁니다**. 기존 Ontology에 수동으로 추가한 정의를 보존/병합하지 않으므로 먼저 버전이나 별도 복사본을 확보해야 합니다.

API 요청 전이나 후에 실패할 수 있습니다. 실행 중 생성된 v4 backing 테이블은 자동 삭제하지 않습니다. 원본/기존 테이블을 덮어쓰거나 자동으로 정리하지 않으며, 재실행 시 v4 테이블과 원본을 비교합니다. 변경이 감지되면 오류를 해결하기 전까지 덮어쓰지 마세요. Ontology 갱신 API는 전체 definition 교체이므로, 기존 Ontology에 수동 추가된 정의가 있다면 실행 전에 백업해야 합니다. `materialize_graph.py`는 연결된 GraphModel만 갱신하고, 다른 GraphModel은 수정하지 않습니다. 기존 GraphModel에 이 스크립트와 다른 projection이 있으면 덮어쓰지 않고 중단합니다. Fabric Graph는 Decimal 속성을 지원하지 않으므로, 그래프에서는 해당 금액 속성을 원본 `_raw` 문자열 열에서 `STRING`으로 제공합니다. Ontology의 Decimal 형식과 Lakehouse `decimal(38,6)` 값은 그대로 보존됩니다. Fabric은 GraphModel의 eligibility 검사를 위한 공개 REST API를 제공하지 않으므로 스크립트는 OneLake 바인딩·키·컬럼을 사전 검사하고, 이후 materialization과 실제 graph query로 결과를 검증합니다.

기존 materialized graph를 변경 없이 재검사할 때는 [명령 예시](README.md#complete-track1-automatically)에서 `--apply` 대신 `--verify-only`를 지정합니다. 이는 정의·타입과 두 쿼리만 검사하므로 전체 데이터나 Ontology UI 상태 검증과 구분합니다.

## 로컬 검증

Python 3에서 TMDL payload와 배포 스크립트를 검증합니다. Fabric 리소스/파일/Notebook 게시 API는 로컬 통합 스크립트가 Azure CLI 인증으로 호출합니다. Ontology 생성 API와 Lakehouse 데이터 검증은 Fabric Notebook에서 실행합니다.

```bash
python3 -m unittest discover -s tests -p 'test_ontology_fabric.py' -v
python3 -m unittest discover -s tests -p 'test_fabric_notebook_upload.py' -v
python3 -m unittest discover -s tests -p 'test_fabric_deploy.py' -v
python3 -m py_compile track1/create_ontology_fabric.py
python3 -m py_compile track1/upload_fabric_notebooks.py
python3 -m py_compile track1/deploy_fabric.py
```

## API 및 공식 참고

- [Tutorial prerequisites](https://learn.microsoft.com/en-us/fabric/iq/ontology/tutorial-0-introduction#prerequisites) — 용량과 테넌트 설정
- [Create Ontology REST API](https://learn.microsoft.com/en-us/rest/api/fabric/ontology/items/create-ontology) — `POST /v1/workspaces/{workspaceId}/ontologies`, Contributor 권한, Preview/LRO
- [List Ontologies REST API](https://learn.microsoft.com/en-us/rest/api/fabric/ontology/items/list-ontologies) — 중복 이름 확인과 generation 조회
- [Get Lakehouse REST API](https://learn.microsoft.com/en-us/rest/api/fabric/lakehouse/items/get-lakehouse) — SQL endpoint 연결 정보
- [Ontology public definition](https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/ontology-definition) — TMDL, DirectLake 테이블·엔터티·관계 정의
- [Get Ontology Definition REST API](https://learn.microsoft.com/en-us/rest/api/fabric/ontology/items/get-ontology-definition) — 생성 후 정의 검증
- [NotebookUtils credentials](https://learn.microsoft.com/en-us/fabric/data-engineering/notebookutils/notebookutils-credentials) — Notebook의 Fabric API 토큰
- [Long-running operations](https://learn.microsoft.com/en-us/rest/api/fabric/articles/long-running-operation) — 202 응답 및 작업 상태 처리
- [GraphModel public definition](https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/graph-model-definition) — 그래프 데이터 원본, 노드, 관계 정의
- [GraphModel update definition](https://learn.microsoft.com/en-us/rest/api/fabric/graphmodel/items/update-graph-model-definition) — projection 설정
- [Graph refresh job](https://learn.microsoft.com/en-us/rest/api/fabric/graphmodel/background-jobs/run-on-demand-refresh-graph) — materialize/refresh
- [Graph query API](https://learn.microsoft.com/en-us/rest/api/fabric/graphmodel/items/execute-query(beta)) — 완료 후 GQL 검증
- [Graph limitations](https://learn.microsoft.com/en-us/fabric/graph/limitations) — 지원 데이터 형식
