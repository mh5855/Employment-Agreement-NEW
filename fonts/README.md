# 한글 폰트 안내

## Windows 환경
Windows에는 맑은 고딕 폰트(`C:\Windows\Fonts\malgun.ttf`)가 기본 설치되어 있어
별도 폰트 설치 없이 바로 사용 가능합니다.

## Linux / Mac 환경
아래 중 하나를 이 폴더(`fonts/`)에 복사해 주세요.

### 나눔고딕 (권장)
```bash
# Ubuntu/Debian
sudo apt-get install fonts-nanum
cp /usr/share/fonts/truetype/nanum/NanumGothic.ttf ./fonts/
cp /usr/share/fonts/truetype/nanum/NanumGothicBold.ttf ./fonts/
```

### 직접 다운로드
구글 폰트에서 Nanum Gothic을 다운로드하여 이 폴더에 위치:
- NanumGothic.ttf
- NanumGothicBold.ttf (없으면 일반체로 대체됨)
