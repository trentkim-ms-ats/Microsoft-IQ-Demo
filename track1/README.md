# Track1 · FabricIQ

**목적:** 작은 주문 데이터로 내부 수치를 계산하고 그 수치가 어떤 엔터티·관계를 거쳤는지 보여줍니다. 최소 구성은 `CSV → Lakehouse Delta 테이블 → SQL baseline → Ontology`입니다.

## 포함 자산과 로컬 실행

- [합성 CSV](data/): 8개 테이블, 주문 8건, 가상 상품 3종. 원본 워크숍 CSV와 호환되지 않습니다.
- [데이터 사전](data/README.md): 키·단위·분모 정의.
- [Fabric 적재 코드](load_fabric.py): Fabric Notebook에 붙여 실행하는 Spark 코드.
- [기준 SQL](queries.sql): Q1~Q3 쿼리.
- [Ontology 매핑](ontology.json): 사람이 구성할 엔터티/관계 명세. 제품 배포용 API 번들이 아닙니다.

```bash
python3 tools/demo.py --track fabric
```

`outputs/fabric.json`에 질문별 수치와 원본 CSV 경로가 생깁니다.

## live 구축: 최소 순서

1. [공통 사전조건](../docs/SETUP.md)을 확인합니다. Fabric 용량이 연결된 데모 Workspace에서 Lakehouse 하나와 Notebook 하나를 만듭니다. Ontology Preview가 지원되지 않으면 SQL 데모까지만 가능하다고 표시합니다.
2. `data/`의 **CSV 8개만** Lakehouse `Files/iq-demo/`에 업로드합니다. README나 원본 워크숍 자료는 업로드할 필요가 없습니다.
3. Notebook을 해당 Lakehouse에 기본 연결하고 세션을 시작합니다. [적재 코드](load_fabric.py)를 Python 셀에 붙여 실행합니다. 기본 경로는 `/lakehouse/default/Files/iq-demo`이며 다르면 `DATA_ROOT` 한 곳을 바꿉니다. `demo_` 접두사의 Delta 테이블을 생성합니다. 같은 테이블이 있으면 덮어쓰지 않고 실패합니다.
4. [SQL](queries.sql)의 Q1~Q3를 Notebook의 `%%sql` 셀에서 **쿼리별로** 실행합니다. SQL analytics endpoint를 쓰면 테이블 동기화를 기다린 뒤 같은 테이블을 조회합니다.
5. 포털에서 Ontology를 만들고 [매핑 명세](ontology.json)에 있는 엔터티를 추가합니다. 각 `key`를 식별 키에, `properties`를 같은 테이블 컬럼에 바인딩한 뒤 `relationships`의 양끝 키를 연결합니다. 실제 생성된 item ID와 이름은 로컬 운영 기록에만 보관합니다. 명세 JSON을 제품 API에 직접 POST하지 않습니다.
6. `Campaign → Order → Payment`, `Order → Shipment/Return/Ticket`, `Product → OrderLine` 경로를 탐색합니다. UI의 지원 범위가 다르면 SQL 관계로 설명하고 실제 Ontology 탐색이 미검증임을 밝힙니다.

## 시연·확인

Q1은 `WaveDemo` 50%, `LoyaltyDemo` 75%입니다. **방문자 대비 전환율이 아니라 주문 대비 승인율**입니다. Q2는 배송 지연 주문의 반품/문의 비율을 비교합니다. Q3는 상품별 승인 주문 매출과 배송 주문의 반품률을 보여줍니다. 합성 상관관계이지 원인 증거가 아닙니다.

다음 [WorkIQ](../track2/README.md)에 캠페인·상품 이름, [데이터 사전](data/README.md)의 분모, SQL 결과를 전달합니다. live는 Workspace/Ontology 식별자와 실제 매핑도 별도 전달합니다.

## 정리

이번에 만든 `demo_` 테이블과 Ontology/Notebook만 제거합니다. 공유 Lakehouse 전체를 삭제하지 않습니다. 전용 용량은 [비용·정리](../docs/SETUP.md)에 따라 처리합니다.
