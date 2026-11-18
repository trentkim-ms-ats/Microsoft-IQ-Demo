# Microsoft IQ Demo

워크숍 전체를 따라가지 않고 **4개 트랙의 데모 환경을 구축·시연**하기 위한 한국어 구현 패키지입니다. 코드, 작은 합성 데이터, 서비스별 수동 구축 순서를 함께 제공합니다.

| 순서 / 시작점 | 데모에서 보여줄 결과 | 필요한 서비스 |
| --- | --- | --- |
| [1. FabricIQ](track1/README.md) | 결제 승인율, 배송·반품 비교, 상품별 매출을 계산하고 엔터티 관계로 설명 | live: Fabric Lakehouse, Notebook, Ontology |
| [2. WorkIQ](track2/README.md) | 같은 주제를 다루는 M365 근거를 사용자 권한 범위에서 검색 | live: SharePoint, Outlook, Teams, OneDrive 및 승인된 검색 도구 |
| [3. WebIQ](track3/README.md) | 내부 정보를 외부로 보내지 않고 공개 출처와 해석 한계 제시 | live: 승인된 Foundry Web Search |
| [4. FoundryIQ](track4/README.md) | 세 근거를 구분해 결합하고 일부 소스 장애 때 부분응답·차단 | live: Foundry 프로젝트·모델, 지식 연결과 도구 어댑터 |

위 명칭은 [참조 워크숍](https://github.com/trentkim-ms-ats/microsoft-iq-workshop)의 트랙 구분입니다. 이 저장소의 Python 코드는 제품 SDK나 실제 IQ 서비스를 대체하지 않는 **오프라인 시뮬레이터**입니다.

## 가장 짧은 실행 경로: 키·과금 없는 로컬 데모

Python **3.10 이상**만 필요합니다. 추가 패키지, 로그인, Azure/M365 연결은 없습니다. 저장소 루트에서 실행하세요.

```bash
python3 tools/demo.py
python3 tools/demo.py --mode web-down
python3 tools/demo.py --mode internal-down
python3 tools/demo.py --role guest
python3 -m unittest discover -s tests -v
```

첫 명령은 4개 트랙 입력을 읽어 `outputs/fabric.json`, `outputs/work.json`, `outputs/web.json`, `outputs/responses/normal-presenter.json`을 생성합니다. 후속 실행은 마지막 실행의 중간 파일을 갱신하고 모드·역할별 응답 파일은 따로 보존합니다. `outputs/`는 Git에서 제외됩니다. 생성 파일을 수정해 입력으로 쓰지는 않습니다.

**볼 것:** 정상 응답의 Q1~Q3 수치와 근거 경로 → `web-down`의 외부 근거 경고 → `internal-down`의 `blocked` → `guest`에서 제한 문서 제외. 상세 [시연 순서](docs/DEMO.md)와 [검증 범위](docs/VALIDATION.md)를 참고하세요.

## 실제 서비스를 구축하려면

공통 준비는 [환경·비용·정리](docs/SETUP.md)를 먼저 읽고, 각 트랙 README의 **live 구축**을 순서대로 진행합니다. 저장소는 리소스 생성, 관리자 동의, 메일 전송, 외부 검색을 자동 실행하지 않습니다.

의존성은 `Track1의 키·지표 → Track2의 동일 키 업무 문서 → Track3의 일반화된 외부 질문 → Track4 결합`입니다. 로컬은 모든 합성 입력이 포함되어 어느 트랙부터도 실행할 수 있지만, live에서는 앞 트랙의 결과와 권한 확인이 먼저 필요합니다.

| 질문 | 정형 신호 | 내부 근거 | 외부 참고 |
| --- | --- | --- | --- |
| Q1 | 캠페인별 주문 결제 승인율 | 결제 점검 메모·메일 | 결제 서비스 공식 상태 페이지 |
| Q2 | 배송 지연 여부별 반품·문의 | 물류 대화·정책 메모 | 공식 기상·교통 정보 |
| Q3 | 가상 상품 3종의 매출·반품 | 상품 검토·회의 메모 | 제품 안전·보안 지침 |

**축약 기준:** 강의, 미션 제출, 학습 질문, 산업 Playground, 강사용 답안, 전체 샘플 확장, 일일 자동화는 제외했습니다. 원본의 14개 CSV/대량 업무 콘텐츠 대신 이 데모 질문에 필요한 8개 테이블과 6개 업무 항목, 6개 외부 출처 fixture만 독립적으로 만들었습니다. 원본 호환 패키지가 아니며 원본 생성기·온톨로지 번들·실환경 식별자는 포함하지 않습니다.

## 출처와 공개 범위

[출처·재배포 판단](SOURCES.md)에 참조 커밋과 문서를 고정했습니다. 참조 원본에서 라이선스 파일을 확인하지 못해 **원문 코드·문서·데이터·이미지를 복제하지 않았습니다**. 이 저장소의 설명, 코드, 수치는 새로 작성한 예제이며 실제 고객·상품·운영 사건을 나타내지 않습니다. 외부 URL은 참고 위치일 뿐 최신 사실 확인이나 인용 허락을 의미하지 않습니다.

실서비스 프로비저닝, M365 실제 ACL/색인, Fabric Ontology Preview, 웹 최신성, Foundry Responses API 및 모델 품질은 **별도 환경에서 검증해야 합니다**. live 어댑터는 포함하지 않으며 필요한 계약과 수동 연결 절차를 명시했습니다.
