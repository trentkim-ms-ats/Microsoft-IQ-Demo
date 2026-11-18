# 합성 정형 데이터

실제 계정·고객·운영 데이터를 사용하지 않았습니다. 고정 기간은 2026-01-10~12, 통화는 KRW입니다. 모든 주문은 하나의 캠페인에만 속하고 결제는 주문당 한 행입니다. 실패 결제 주문은 배송·매출에서 제외됩니다. 반품은 주문/상품 조합당 최대 한 행이고 부분 수량 반품은 없습니다.

| CSV | 키 | 관계 / 의미 |
| --- | --- | --- |
| [campaigns.csv](campaigns.csv) | campaign_id | 캠페인 2개 |
| [products.csv](products.csv) | product_id | 가상 상품 3개 |
| [orders.csv](orders.csv) | order_id | campaign_id 참조, 주문 8건 |
| [payments.csv](payments.csv) | payment_id | order_id 유일, approved/failed |
| [order_items.csv](order_items.csv) | order_id + product_id | quantity, unit_price_krw |
| [shipments.csv](shipments.csv) | shipment_id | order_id 유일, delayed는 0/1 |
| [returns.csv](returns.csv) | return_id | order_id + product_id 참조 |
| [support_tickets.csv](support_tickets.csv) | ticket_id | order_id 참조 |

Q1 = 승인 결제 주문수 / 전체 주문수. 취소·미결제 상태 확장은 하지 않습니다.

Q2 = 배송된 주문 중 delayed 값별 반품이 있는 **서로 다른 주문수** / 배송 주문수. 문의 비율도 티켓 수가 아닌 티켓이 있는 주문수 기준입니다.

Q3 = 승인 결제 주문의 `quantity × unit_price_krw` 합계(반품 차감 전 매출). 반품률 = 해당 상품이 배송된 주문 중 해당 상품 반품 주문수 / 해당 상품 배송 주문수. 판매 수량 대비 반품 수량 비율이 아닙니다.

집계 시 반품과 티켓을 직접 다대다 JOIN하지 않습니다. 각 주문/상품의 존재 여부로 집계하여 중복 증폭을 막습니다. 결측·중복·고아 참조는 시뮬레이터에서 오류로 처리합니다.
