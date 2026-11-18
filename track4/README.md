# Track4 · FoundryIQ

**목적:** FabricIQ의 숫자, WorkIQ의 권한 내 근거, WebIQ의 공개 출처를 구분한 최종 응답과 장애 동작을 보여줍니다. 최소 구성은 `세 소스 도구 + 권위 지식 → 라우팅/결합 → 근거 검사 → 최종 응답`입니다.

## 포함 자산과 로컬 실행

- [scenarios.json](scenarios.json): Q1~Q3의 책임과 한계.
- [agent-instructions.txt](agent-instructions.txt): 별도 Foundry 에이전트 구성 시 사용할 독립 작성 지침.
- [정의·정책 문서](knowledge/definitions.md): live에서 권위 지식 연결을 만들 때 넣을 최소 예제.
- [로컬 러너](../tools/demo.py): 실제 LLM 없이 규칙 기반으로 결합합니다.
- [도구 계약](contracts.md): 직접 구현해야 할 live 어댑터 경계와 결과 필드.

```bash
python3 tools/demo.py --track foundry
python3 tools/demo.py --mode fabric-down
python3 tools/demo.py --mode work-down
python3 tools/demo.py --mode web-down
python3 tools/demo.py --mode internal-down
python3 tools/demo.py --mode all-down
```

각 실행은 `outputs/responses/<모드>-<역할>.json`을 만듭니다. 정상은 `complete`, 한 소스 실패는 `partial`, Fabric과 Work가 모두 실패하면 `blocked`입니다. 실패한 소스의 근거/숫자는 응답에 남기지 않습니다. 차단일 때 웹 목록은 진단용으로 남을 수 있지만 내부 분석은 `null`입니다. 이 러너는 **상태 계약 시뮬레이션**이지 API 장애를 실제 주입한 네트워크 테스트가 아닙니다.

## live 구축: 최소 순서

1. 앞의 [FabricIQ](../track1/README.md), [WorkIQ](../track2/README.md), [WebIQ](../track3/README.md)에서 실제 연결과 권한 확인을 마칩니다. [공통 설정](../docs/SETUP.md)의 프로젝트·모델 접근 권한과 할당량을 확인합니다.
2. 승인된 Foundry 프로젝트에서 지원되는 모델 배포를 선택하고 에이전트를 만듭니다. [지침](agent-instructions.txt)을 instructions로 설정합니다. API 버전·SDK·모델 이름은 실제 프로젝트 지원 값으로 결정하며 이 저장소에 테넌트 값을 커밋하지 않습니다.
3. [정의 문서](knowledge/definitions.md)를 지원되는 Foundry IQ/지식 소스(환경에 따라 AI Search 등)에 등록하고 에이전트의 읽기 연결을 구성합니다. 정의 조회 질의를 실행해 단순 프롬프트 주입과 실제 지식 검색을 구분합니다. 지식 서비스가 없다면 `Foundry 지식 검색 미연결`로 표시합니다. 로컬은 이 파일을 응답에 첨부할 뿐 검색 서비스를 구현하지 않습니다.
4. [계약](contracts.md)에 맞는 Fabric/Work 어댑터를 **별도로 구현**하고 승인된 도구 연결로 등록합니다. Fabric 쿼리는 고정 Q1~Q3만 허용하고 Work는 호출 사용자 권한을 보존합니다. 원시 SQL/Graph URL을 계약 endpoint로 지정해서는 안 됩니다. Web은 지원되는 native Web Search 사용을 우선하고 내부 컨텍스트가 검색어로 유출되지 않도록 분리합니다.
5. 세 도구의 명시적 성공/실패를 받아 결합합니다. 인증·권한·스키마 오류는 즉시 실패 처리합니다. 일시적 429/5xx만 최초 호출 후 5/10/20초 대기로 최대 3회 추가 시도합니다. 로컬 러너는 외부 호출이 없어 대기/재시도하지 않습니다.
6. 최종 문장화가 필요하면 프로젝트에서 지원하는 **Responses API**를 사용합니다. 키는 `api-key`, Entra 토큰은 `Authorization: Bearer`에만 전달하고 로그에 남기지 않습니다. endpoint/model/인증값은 환경 또는 비밀 저장소에서 주입합니다. 이 저장소는 live 호출 클라이언트를 포함하지 않습니다.
7. Q1~Q3마다 수치·내부 원본 링크·외부 URL·미확인 사항을 검토합니다. [실패 정책](contracts.md)과 동일하게 한 소스 및 두 내부 소스 장애를 검증합니다. 모델이 출처에 없는 단정·수치·실행을 추가하면 시연 준비 미완료입니다.

## 시연·정리

[10분 시연](../docs/DEMO.md) 순서로 정상/외부 누락/내부 차단/역할 필터를 보여줍니다. 응답의 `executionMode=simulation`과 `humanApprovalRequired=true`를 확인합니다.

실서비스 검증은 [별도 체크리스트](../docs/VALIDATION.md)를 따릅니다. 시연 후 전용 에이전트·지식 연결·검색 인덱스·불필요한 모델 배포와 테스트 권한을 정리합니다. 공유 리소스나 조직 공용 지식은 삭제하지 않습니다.
