# 원본 14개 테이블의 Ontology 설계 초안

이 문서는 Fabric 배포 파일이 아닙니다. 원본에는 의도된 중복·결측·고아 참조가 있으므로 먼저 품질을 검토하고 키가 유일한 표준화 뷰를 만든 다음, 실제 지원 기능에 맞게 식별자와 관계를 바인딩하세요. 원본 CSV를 덮어쓰거나 오류가 없다고 가정하지 않습니다.

| 엔터티 후보 | 원본 테이블 | 식별자 후보 |
| --- | --- | --- |
| Channel | `workshop_channels` | `channel_id` |
| Customer | `workshop_customers` | `customer_id` |
| Product | `workshop_products` | `product_id` |
| Campaign | `workshop_campaigns` | `campaign_id` |
| Promotion | `workshop_promotions` | `promotion_id` |
| Order | `workshop_orders` | `order_id` |
| OrderItem | `workshop_order_items` | `order_id` + `product_id` 후보, 유일성 확인 필요 |
| Payment | `workshop_payments` | `payment_id` |
| Shipment | `workshop_shipments` | `shipment_id` |
| Return | `workshop_returns` | `return_id` |
| InventorySnapshot | `workshop_inventory_snapshots` | `snapshot_id` |
| OrderPromotion | `workshop_order_promotions` | `order_id` + `promotion_id` 후보, 유일성 확인 필요 |
| CampaignAttribution | `workshop_campaign_attribution` | 원본에 단일 ID 없음; 귀속 모델을 포함한 복합 키의 유일성을 검토 |
| SupportTicket | `workshop_support_tickets` | `ticket_id` |

기본 관계는 Order→Customer/Channel, Campaign→Channel, OrderItem→Order/Product, Payment/Shipment→Order, Return→Order/Product/Customer, InventorySnapshot→Product, OrderPromotion→Order/Promotion, CampaignAttribution→Campaign/Order/Customer, SupportTicket→Order/Customer입니다. 브리지 테이블을 제거하지 않아 캠페인·프로모션의 다대다 관계를 보존합니다.

복합 키의 충돌이나 고아 참조가 있으면 실제 관계 바인딩 전에 해결 정책을 정하고, 행 누락과 집계 차이를 별도 기록하세요. Ontology 생성·바인딩·탐색은 실제 환경에서 별도로 검증해야 합니다.
