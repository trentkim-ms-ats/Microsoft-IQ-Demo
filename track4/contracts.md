# live 경계와 로컬 응답 계약

이 문서는 **독립 예제 계약**입니다. Microsoft 제품의 공식 REST schema 또는 원본 workshop adapter와의 호환성을 뜻하지 않습니다. live 어댑터는 포함하지 않았습니다.

## 별도 구현할 도구

도구 요청에는 `scenarioId`(Q1~Q3), `question`, `semanticKeys`를 전달할 수 있습니다. Work의 사용자 식별/권한은 요청 본문의 임의 `role`이 아니라 인증된 호출 문맥에서 검증합니다. `semanticKeys`를 Web Search에 그대로 전달하지 않습니다.

| 도구 | 성공 시 필요한 내용 | 실제 연결 |
| --- | --- | --- |
| FabricIQ | 지표/분모/단위/조회 시점/테이블 추적 | Lakehouse SQL 또는 검증된 Ontology 경로 |
| WorkIQ | 현재 사용자에게 허용된 evidence ID/본문 요약/원본 URL/수정 시각/소스 종류 | 승인된 M365 검색 또는 소스별 조회, 실제 ACL 유지 |
| WebIQ | title/url/domain/observedAt/scope/factStatus/limitations | 승인된 native Web Search 또는 별도 adapter |

스키마 누락, HTTP 오류, 401/403은 실패입니다. 성공했지만 검색 결과가 0건인 경우는 실패와 구별하여 `no-evidence`와 이유를 기록하고 응답에서 근거 부재를 밝힙니다. 실패를 빈 배열의 정상 응답으로 변환하지 마세요. 민감한 오류 본문·토큰은 로그에 보관하지 않습니다.

## 장애 정책

| 실패 | 결과 | 필수 경고 |
| --- | --- | --- |
| Fabric만 | partial | 정형 수치 미검증 |
| Work만 | partial | 업무 문서 근거 없음 |
| Web만 | partial | 외부 최신 근거 없음 |
| Fabric + Work | blocked | 내부 근거 부족으로 분석 차단 |
| 전부 | blocked | 모든 소스 실패 및 분석 차단 |

성공한 소스의 근거만 포함하고 실패한 소스의 예전 캐시를 현재 성공처럼 재사용하지 않습니다. live 재시도는 일시 오류만 5/10/20초, 최초 호출 포함 4회까지입니다.

## 최종 응답 계약 예시

실제 어댑터 구현 시 다음 필드를 질문별로 검토합니다. 현재 통합 응답을 생성하는 로컬 러너는 없습니다.

- `scenarioId`, `question`, `executionMode=simulation`, `status`
- `metrics`: Fabric 집계 목록 또는 실패 시 null
- `evidenceLinks`: role 필터 후 ID/소스/로컬 경로/합성 본문. live 링크 아님
- `webCitations`: fixture URL 목록, `observedAt=null`
- `sourceTrace`: FabricIQ/WorkIQ/WebIQ/FoundryIQ 각각의 상태와 실제 제공된 로컬 자료 참조
- `warnings`, `limitations`, `analysis`, `humanApprovalRequired=true`

실제 지식 검색이나 Responses API를 호출하지 않았다면 그렇게 명시합니다.
