# 환경·비용·정리

## 공통 구성

로컬은 Python 3.10+가 필요합니다. 원본 Track1 CSV를 처음 받을 때 인터넷이 필요하며 결과는 `outputs/`에 기록합니다.

live는 별도 승인된 데모 전용 환경을 사용하세요. 관리자는 아래 항목을 미리 확인하고, 실제 환경값은 Git에 추가하지 않는 로컬 기록으로 관리합니다.

| 범위 | 준비물 / 최소 작업 권한 | 만들거나 기록할 것 |
| --- | --- | --- |
| Fabric | 용량이 연결된 Workspace, Lakehouse·Notebook 생성 권한(일반적으로 Contributor 이상), 지원되는 Ontology Preview | Workspace/Lakehouse/Ontology 식별자, 엔터티-컬럼 매핑 |
| M365 | 샘플 계정 2개, 네 소스 사용 라이선스, 콘텐츠 생성·공유 권한, 조직에서 허용한 검색 도구 | 사이트·폴더·채널·메일의 실제 원본 링크, 사용자별 접근 확인 |
| WebIQ | 승인된 Foundry 프로젝트, 모델, Web Search 가용성·결제 및 정책 승인 | 승인된 검색어, URL, 관찰 시각, 적용 지역/기간 |
| Foundry | 프로젝트·모델 사용 권한과 할당량, 필요 시 별도 AI Search 지식 연결 및 해당 데이터 읽기 권한 | 모델 배포 이름, 연결 이름, 도구 계약과 응답 로그 |

여기서 IQ는 트랙 책임을 뜻하며 단일 공통 API를 의미하지 않습니다. Microsoft Graph의 조회 API, Microsoft 365 검색 도구, Fabric SQL/Ontology, Foundry의 지식 연결은 서로 다른 구성입니다. **서비스 URL을 그대로 이 저장소의 어댑터라고 취급하지 마세요.**

## 권한과 데이터 경계

기본 경로는 포털에서 합성 자료를 수동 업로드하는 방식입니다. 앱 등록·관리자 동의·메일 자동 발송·Teams 자동 게시 스크립트는 의도적으로 제공하지 않습니다.

Graph 기반 별도 커넥터가 필요하면 사용하는 API별로 읽기 권한만 검토하세요. 예를 들어 메일, 파일, 사이트, 채널 메시지 조회에는 각각 `Mail.Read`, `Files.Read.All`, `Sites.Read.All`, `ChannelMessage.Read.All` 등의 권한 검토가 필요할 수 있습니다. **이 목록은 한꺼번에 부여할 권한 세트가 아닙니다.** 위임/앱 전용 지원 여부와 관리자 동의는 선택한 API 문서로 확인하세요. 배포용 쓰기·발송 권한과 런타임 조회 권한은 분리하고, 광범위한 앱 전용 권한으로 사용자 ACL을 우회하지 마세요.

실제 이메일, 고객명, 주문 데이터, 내부 URL, 토큰, 테넌트/구독 식별자는 공개 커밋·스크린샷·이슈에 넣지 않습니다. `example.invalid` 링크와 `presenter`/`guest`는 로컬 가상 값이며 실제 테넌트나 신원 체계가 아닙니다.

## 실행 전 게이트

1. 예산 소유자와 리소스 삭제 책임자를 지정합니다.
2. Fabric/Foundry의 리전·Preview 가용성, 모델 할당량, M365 색인 가능 여부를 포털에서 확인합니다.
3. 실제 데이터가 없는 데모 전용 위치에만 샘플을 넣습니다.
4. 두 사용자로 원본 문서 열기와 검색 결과 차이를 확인한 후 Foundry와 연결합니다.
5. 확인되지 않은 연결은 `미연결`로 표시합니다. 로컬 fixture 결과를 live 성공 증거로 사용하지 않습니다.

## 비용과 정리

로컬 코드는 과금 API를 호출하지 않습니다. live는 Fabric 용량, 모델 토큰, Web Search, AI Search 및 로그 저장에 비용이 발생할 수 있습니다. 정확한 단가는 사용 리전·계약·시점에 따라 달라 고정 금액을 제시하지 않습니다.

시연 후에는 전용 데모 연결·에이전트와 불필요한 모델 배포/검색 리소스를 검토하고, 데모 전용 Fabric 용량은 필요 시 일시 중지 또는 삭제합니다. 공유 리소스는 삭제하지 마세요. M365에서 이번에 추가한 6개 항목과 공유 권한만 제거하고 메일은 받은 편지함/보낸 편지함·휴지통 및 보존 정책도 확인합니다. 부여한 테스트 권한을 철회하고 토큰을 폐기합니다.

## 제품 문서

- [Fabric Lakehouse](https://learn.microsoft.com/fabric/data-engineering/lakehouse-overview)
- [Microsoft Graph 권한](https://learn.microsoft.com/graph/permissions-reference)
- [Microsoft 365 Copilot 검색 API](https://learn.microsoft.com/microsoft-365-copilot/extensibility/api/ai-services/retrieval/overview)
- [Foundry Agent Service](https://learn.microsoft.com/azure/ai-foundry/agents/overview)
- [Foundry Responses API](https://learn.microsoft.com/azure/ai-foundry/openai/how-to/responses)

API/Preview와 포털 메뉴는 변경될 수 있습니다. 위 공식 문서와 실제 테넌트 지원 상태를 우선하세요.
