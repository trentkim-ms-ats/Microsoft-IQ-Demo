# 10분 시연 순서

미리 저장소 루트에서 `python3 tools/demo.py`를 실행합니다. 출력은 **고정 합성 데이터**이며 실제 서비스나 현재 외부 사건을 보여주지 않는다고 먼저 밝힙니다.

| 시간 | 동작 | 보여줄 결과 |
| --- | --- | --- |
| 0~2분 | [Track1 데이터](../track1/data/)와 `outputs/fabric.json` 열기 | WaveDemo 승인 2/4=50%, LoyaltyDemo 3/4=75% |
| 2~4분 | [Track2 문서 목록](../track2/data/catalog.json)과 `outputs/work.json` 열기 | 지표와 별개인 내부 근거의 ID·본문·로컬 경로 |
| 4~5분 | [Track3 fixture](../track3/data/citations.json)와 `outputs/web.json` 열기 | 시나리오별 공식 URL 2개, 관찰 시각 null, 현재 사실 아님 |
| 5~7분 | `outputs/responses/normal-presenter.json` 열기 | 질문별 세 근거, 한계, `sourceTrace`, 사람 승인 필요 |
| 7~8분 | `python3 tools/demo.py --mode web-down` | 응답 `partial`, 외부 최신 근거 없음 경고 |
| 8~9분 | `python3 tools/demo.py --mode internal-down` | 내부 두 소스 실패이면 웹이 있어도 `blocked`, 내부 분석 생략 |
| 9~10분 | `python3 tools/demo.py --role guest` | 제한 문서 3개가 결과·추적 정보에서 제외되고 공개 역할용 문서 3개만 남음 |

정상 응답으로 돌아가려면 `python3 tools/demo.py`를 다시 실행합니다.

Q2 기대값은 지연 배송 2건 중 반품 2건(100%), 정시 배송 3건 중 반품 0건(0%)입니다. 비교 집단이 작고 합성된 상관관계이므로 인과성을 주장하지 않습니다. Q3의 매출은 승인 결제 주문의 주문 항목 합계이며 반품 차감 전입니다.

live 시연에서는 JSON 대신 Fabric 쿼리 결과, 실제 M365 원본 링크/두 사용자 검색, Web Search citation, Foundry 응답을 보여줍니다. 이 네 확인을 끝내지 않았다면 `서비스 연동 완료`라고 소개하지 마세요. live의 실패·권한 오류를 fixture로 바꿔 성공처럼 보여주면 안 됩니다.
