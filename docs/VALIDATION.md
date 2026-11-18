# 검증 범위

## 로컬 재현

```bash
python3 -m unittest discover -s tests -v
python3 tools/demo.py
python3 tools/demo.py --mode fabric-down
python3 tools/demo.py --mode work-down
python3 tools/demo.py --mode web-down
python3 tools/demo.py --mode internal-down
python3 tools/demo.py --mode all-down
python3 tools/demo.py --role guest
```

테스트는 합성 데이터 참조 관계·집계값, 역할 필터, citation 허용 도메인/fixture 표시, 장애 시 응답·근거 제거, 깨진 로컬 문서 링크를 확인합니다. 입력이 없거나 계약을 벗어나면 예외와 nonzero 종료로 실패를 드러냅니다. 네트워크·비밀값·외부 패키지를 사용하지 않습니다.

`track1/load_fabric.py`는 Fabric Spark 세션 전용이므로 로컬은 문법만 확인할 수 있습니다. SQL은 같은 합성 데이터로 SQLite에서 실행해 집계 의미를 비교하지만 Fabric 엔진 동작을 증명하지 않습니다.

## 별도 live 검증: 여기서는 실행하지 않음

| 항목 | 통과 증거 |
| --- | --- |
| Fabric | 8개 Delta 테이블 생성, Notebook/SQL과 로컬 수치 일치, 실제 Ontology 관계 탐색 |
| WorkIQ | 네 소스의 실제 원본 링크, 색인 후 질의 재현, 허용 사용자 열람과 차단 사용자 미노출 |
| WebIQ | 승인된 외부 검색 실행 로그, 실제 URL·관찰 시각·지역·기간 및 해석 한계 |
| FoundryIQ | 별도 구현한 인증/ACL 어댑터의 실응답, 지식 연결, Responses API 요청/응답, 장애·재시도 |

LLM의 문장 품질·환각 여부, 실제 서비스의 사용자 권한 상속, 최신 외부 사실, 과금 리소스 상태를 로컬 테스트 통과로 보증하지 않습니다. 이 저장소는 live 어댑터·인프라 템플릿·자동 배포를 제공하지 않습니다.
