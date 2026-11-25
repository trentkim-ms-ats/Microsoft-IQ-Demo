# 원본 14개 테이블의 Ontology 모델

이 문서는 Fabric 배포 파일이 아니라 자동 생성 모델의 개요입니다. 실제 TMDL 정의와 REST API 자동화는 [자동 생성 안내](ONTOLOGY_AUTO_CREATE.md)와 `create_ontology_fabric.py`를 참고하세요. 원본 CSV와 `workshop_` 테이블을 덮어쓰지 않습니다. 네 개의 복합/중복 키 테이블은 원본 행을 보존한 helper Delta 테이블에 결정적 합성 식별자를 추가해 바인딩합니다.

| 엔터티 | 원본 테이블 | 사용 식별자 |
| --- | --- | --- |
| Channel | `workshop_channels` | `channel_id` |
| Customer | `workshop_customers` | `customer_id` |
| Product | `workshop_products` | `product_id` |
| Campaign | `workshop_campaigns` | `campaign_id` |
| Promotion | `workshop_promotions` | `promotion_id` |
| Order | `workshop_orders` | `order_id` |
| OrderItem | `workshop_order_items` | 합성 `ontology_entity_id` |
| Payment | `workshop_payments` | `payment_id` |
| Shipment | `workshop_shipments` | 합성 `ontology_entity_id` |
| Return | `workshop_returns` | `return_id` |
| InventorySnapshot | `workshop_inventory_snapshots` | `snapshot_id` |
| OrderPromotion | `workshop_order_promotions` | 합성 `ontology_entity_id` |
| CampaignAttribution | `workshop_campaign_attribution` | 합성 `ontology_entity_id` |
| SupportTicket | `workshop_support_tickets` | `ticket_id` |

기본 관계는 Order→Customer/Channel, Campaign→Channel, OrderItem→Order/Product, Payment/Shipment→Order, Return→Order/Product/Customer, InventorySnapshot→Product, OrderPromotion→Order/Promotion, CampaignAttribution→Campaign/Order/Customer, SupportTicket→Order/Customer입니다. 브리지 테이블을 제거하지 않아 캠페인·프로모션의 다대다 관계를 보존합니다.

원본에는 `order_items` 복합 키 중복 3행, `shipments.shipment_id` 중복 1행이 있습니다. 또 `payments.order_id`와 `support_tickets.customer_id`에서 각각 참조 대상이 없는 값이 한 건씩 있습니다. 자동화는 이 행들을 수정·제거하지 않고 보고하며, 관계 연결 시 고아 참조가 매칭되지 않는 점을 유의하세요. 검증 범위와 Ontology UI 상태의 한계는 [라이브 검증](../docs/VALIDATION.md#live-acceptance-gates)을 확인하세요.
