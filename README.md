# Microsoft IQ Demo

워크숍의 **4개 트랙 데모 환경을 구축·시연**하기 위한 한국어 구현 패키지입니다. Track1은 원본 워크숍의 14개 CSV와 Q1~Q5를 사용합니다. Track2~4의 예제는 아직 원본 Track1 데이터와 연결되지 않았습니다.

| 순서 / 시작점 | 데모에서 보여줄 결과 | 필요한 서비스 |
| --- | --- | --- |
| [1. FabricIQ](track1/README.md) | 원본 14개 테이블과 Q1~Q5 분석 | live: Fabric Lakehouse, Notebook, Ontology |
| [2. WorkIQ](track2/README.md) | 같은 주제를 다루는 M365 근거를 사용자 권한 범위에서 검색 | live: SharePoint, Outlook, Teams, OneDrive 및 승인된 검색 도구 |
| [3. WebIQ](track3/README.md) | 내부 정보를 외부로 보내지 않고 공개 출처와 해석 한계 제시 | live: 승인된 Foundry Web Search |
| [4. FoundryIQ](track4/README.md) | 세 근거를 구분해 결합하고 일부 소스 장애 때 부분응답·차단 | live: Foundry 프로젝트·모델, 지식 연결과 도구 어댑터 |

위 명칭은 [참조 워크숍](https://github.com/trentkim-ms-ats/microsoft-iq-workshop)의 트랙 구분입니다. 로컬 코드는 실제 IQ 서비스를 대체하지 않습니다.

## Track1: 원본 데이터 실행

Python 3.10 이상과 최초 다운로드 시 인터넷 연결이 필요합니다.

```bash
python3 track1/workshop.py download
python3 track1/workshop.py analyze
python3 -m unittest discover -s tests -v
```

원본 14개 파일은 `track1/data/`, Q1~Q5 결과는 `outputs/workshop-track1.json`에 저장됩니다. 고정 원본 커밋의 SHA-256과 행 수를 확인합니다. 원본 파일을 공개 배포하기 전에는 권리를 확인하세요. 상세 정의와 Fabric 적재 방법은 [Track1](track1/README.md)을 참고하세요.

## 실제 서비스를 구축하려면

공통 준비는 [환경·비용·정리](docs/SETUP.md)를 먼저 읽고, 각 트랙 README의 **live 구축**을 순서대로 진행합니다. 저장소는 리소스 생성, 관리자 동의, 메일 전송, 외부 검색을 자동 실행하지 않습니다.

의존성은 `Track1의 키·지표 → Track2의 동일 키 업무 문서 → Track3의 일반화된 외부 질문 → Track4 결합`입니다. 현재 Track2~4 예제는 Track1 원본 데이터와 정합성을 맞추지 않았으므로 결합 데모에 그대로 사용하지 마세요. 자세한 [시연 범위](docs/DEMO.md)와 [검증 범위](docs/VALIDATION.md)를 참고하세요.

## 출처와 공개 범위

[출처·재배포 판단](SOURCES.md)에 참조 커밋과 문서를 고정했습니다. 원본 CSV는 원본 저장소에서 가져온 것입니다. 외부 URL은 참고 위치일 뿐 최신 사실 확인이나 인용 허락을 의미하지 않습니다.

실서비스 프로비저닝, M365 실제 ACL/색인, Fabric Ontology Preview, 웹 최신성, Foundry Responses API 및 모델 품질은 **별도 환경에서 검증해야 합니다**. live 어댑터는 포함하지 않으며 필요한 계약과 수동 연결 절차를 명시했습니다.
