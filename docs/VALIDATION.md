# 검증 범위

## 로컬 재현

```bash
python3 track1/workshop.py download
python3 track1/workshop.py analyze
python3 -m unittest discover -s tests -v
```

Track1 테스트는 원본 14개 CSV의 해시·행 수 및 Q1~Q5 결과 형태와 주요 신호를 확인합니다. 다운로드 전에는 원본 데이터 집계 테스트가 건너뛰어지므로 전체 Track1 검증으로 간주하지 마세요. 테스트는 실제 Fabric 결과나 Ontology를 증명하지 않습니다.

테스트는 WorkIQ 예제의 역할 필터, WebIQ citation 허용 도메인·fixture 표시, 로컬 문서 링크도 확인합니다. 입력이 없거나 계약을 벗어나면 오류로 처리합니다.

`track1/load_fabric.py`는 Fabric Spark 세션 전용입니다. 로컬 SQLite에서의 원본 데이터 집계는 Fabric 엔진 동작을 증명하지 않습니다.

## Fabric 검증 결과 (2026-11-20)

`IQ_Workshop_Lakehouse`에 원본 CSV 14개를 업로드하고 `workshop_` Delta 테이블 14개의 행 수를 확인했습니다. `IQ_Workshop_Track1_Verify_14` Notebook에서 Q1~Q5의 전체 결과를 로컬 결과와 비교했으며 모두 일치했습니다(결과 행 수 60/2/4/2/81). 기존 `IQ_Workshop_Load_14_CSV` Notebook은 Spark 파일 경로 오류로 실패했으므로 재사용하지 말고 [수정된 적재 코드](../track1/load_fabric.py)를 사용하세요. 검증 Notebook은 현재 생성된 테이블을 조회하는 용도입니다.

Ontology 생성과 관계 탐색은 실행하지 않았습니다. 다른 Workspace나 데이터 버전에서 같은 결과를 보장하지 않습니다.

## 남은 live 검증

| 항목 | 통과 증거 |
| --- | --- |
| Fabric | 실제 Ontology 생성·바인딩·관계 탐색 |
| WorkIQ | 네 소스의 실제 원본 링크, 색인 후 질의 재현, 허용 사용자 열람과 차단 사용자 미노출 |
| WebIQ | 승인된 외부 검색 실행 로그, 실제 URL·관찰 시각·지역·기간 및 해석 한계 |
| FoundryIQ | 별도 구현한 인증/ACL 어댑터의 실응답, 지식 연결, Responses API 요청/응답, 장애·재시도 |

LLM의 문장 품질·환각 여부, 실제 서비스의 사용자 권한 상속, 최신 외부 사실, 과금 리소스 상태를 로컬 테스트 통과로 보증하지 않습니다. 이 저장소는 live 어댑터·인프라 템플릿·자동 배포를 제공하지 않습니다.
