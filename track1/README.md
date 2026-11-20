# Track1 · FabricIQ

원본 워크숍의 **14개 CSV 전체**를 고정 버전으로 가져와 Q1~Q5를 분석합니다. 원본 파일은 `track1/data/`에 있습니다. [출처와 재배포 범위](../SOURCES.md)를 확인하세요.

## 로컬 분석

```bash
python3 track1/workshop.py download
python3 track1/workshop.py analyze
python3 -m unittest discover -s tests -v
```

다운로드와 분석 모두 각 파일의 SHA-256과 행 수를 확인합니다. 다운로드는 기존 파일을 검증하고 덮어쓰지 않으며 누락된 파일만 받습니다. 파일 누락·변조 시 실패합니다. 결과는 `outputs/workshop-track1.json`입니다. macOS의 Python에서 인증서 오류가 발생하면 시스템에 설치된 신뢰할 수 있는 CA 번들을 `SSL_CERT_FILE`로 지정하세요.

원본 테이블은 `channels`, `customers`, `products`, `campaigns`, `promotions`, `orders`, `order_items`, `payments`, `shipments`, `returns`, `inventory_snapshots`, `order_promotions`, `campaign_attribution`, `support_tickets`입니다. 원본의 의도된 중복·결측·참조 오류는 수정하지 않습니다. 따라서 테이블에는 원본 행을 보존하고 집계할 때 관계와 분모를 명시합니다.

## Fabric 적재 및 분석

1. 용량이 연결된 Fabric Workspace에서 Lakehouse와 Notebook을 만들고 Notebook의 기본 Lakehouse를 연결합니다.
2. 검증된 `track1/data/`의 CSV 14개를 Lakehouse의 `Files/` 루트에 업로드합니다. 기존 파일을 덮어쓰지 마세요.
3. [적재 코드](load_fabric.py)를 Notebook Python 셀에서 실행합니다. `workshop_` 테이블 14개가 이미 있으면 중단합니다. 파일 해시와 행 수를 먼저 확인하고 Delta 테이블로 저장한 뒤 행 수를 재확인합니다. 중간 실패 시 이미 생성된 테이블을 확인하고 별도로 정리한 후 재시도합니다.
4. [Q1~Q5 SQL](queries.sql)을 각각 Notebook의 SQL 셀에서 실행하고 로컬 결과와 비교합니다. 스키마는 원본 상태를 보존하기 위해 문자열로 적재합니다. 날짜·숫자·상태는 쿼리 또는 별도 표준화 계층에서 명시적으로 변환합니다.
5. Ontology는 실제 Preview 지원 및 데이터 품질 확인 후 [14개 테이블 설계 초안](ontology.md)을 바탕으로 별도 구성합니다.

## 지표와 해석

| 질문 | 집계 방식과 한계 |
| --- | --- |
| Q1 | 캠페인 귀속 주문을 중복 제거하고 결제 성공/재시도 성공 여부를 주문 단위로 집계합니다. 미확인 상태는 `unknown_orders`로 분리합니다. 방문자 전환율은 아닙니다. |
| Q2 | 배송 상태가 한 번이라도 `Delayed`인 주문과 나머지 주문의 반품·불만 티켓 비율을 비교합니다. 미배송 `InTransit`도 비지연군에 포함됩니다. |
| Q3 | 프로모션 유형별 `net_amount / gross_amount`와 전체 이력에서 2회 이상 주문한 고객 비율을 보여줍니다. 실제 원가 기반 마진이나 프로모션 이후 재구매율이 아닙니다. |
| Q4 | 어느 시점이든 품절 스냅샷이 있는 상품을 포함한 주문의 취소율·주문당 문의를 비교합니다. 주문 시점의 품절 여부나 인과관계를 증명하지 않습니다. |
| Q5 | 채널·등급·반품 사유별 고객을 중복 제거해 전체 이력 기준 반복 주문 비율을 계산합니다. 반품 이후 재구매 여부는 아닙니다. |

원본의 기준 질문과 데이터 설명은 [워크숍 Track1](https://github.com/trentkim-ms-ats/microsoft-iq-workshop/tree/b16d5fd8ed481f86eb47d5d4625268ef65a7793b/track1)을 참고하세요. 원본 CSV에는 의도된 데이터 품질 문제가 있으므로 결과는 데모용 신호이며 운영 의사결정에 사용하지 않습니다.

## 범위

Track2~4의 업무 근거는 원본 데이터와 아직 정합성을 검증하지 않았습니다.
