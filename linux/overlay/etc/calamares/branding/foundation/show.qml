import QtQuick 2.0;
import calamares.slideshow 1.0;

Presentation
{
    id: presentation

    Timer {
        interval: 9000
        running: presentation.activatedInCalamares
        repeat: true
        onTriggered: presentation.goToNextSlide()
    }

    function onActivate() { }
    function onLeave() { }

    Slide {
        Rectangle { anchors.fill: parent; color: "#1a2238" }
        Image { id: l1; source: "logo.png"; width: 96; height: 96; anchors.horizontalCenter: parent.horizontalCenter; y: parent.height * 0.18 }
        Text { anchors.top: l1.bottom; anchors.topMargin: 24; anchors.horizontalCenter: parent.horizontalCenter
               text: "Installing Foundation OS"; color: "white"; font.pixelSize: 26; font.bold: true }
        Text { anchors.horizontalCenter: parent.horizontalCenter; y: parent.height * 0.62; width: parent.width * 0.7
               horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; color: "#c9d3ea"; font.pixelSize: 15
               text: "Sit back - this takes a few minutes. Your new system will be ready to go when it finishes." }
    }
    Slide {
        Rectangle { anchors.fill: parent; color: "#1a2238" }
        Text { anchors.horizontalCenter: parent.horizontalCenter; y: parent.height * 0.3
               text: "Get your apps"; color: "white"; font.pixelSize: 26; font.bold: true }
        Text { anchors.horizontalCenter: parent.horizontalCenter; y: parent.height * 0.45; width: parent.width * 0.75
               horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; color: "#c9d3ea"; font.pixelSize: 15
               text: "The Foundation Store installs Google Chrome, Microsoft 365, Google Drive, Zoom, Spotify and more in one click. Double-click any Windows .exe or .msi installer to install it." }
    }
    Slide {
        Rectangle { anchors.fill: parent; color: "#1a2238" }
        Text { anchors.horizontalCenter: parent.horizontalCenter; y: parent.height * 0.3
               text: "Always up to date"; color: "white"; font.pixelSize: 26; font.bold: true }
        Text { anchors.horizontalCenter: parent.horizontalCenter; y: parent.height * 0.45; width: parent.width * 0.75
               horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; color: "#c9d3ea"; font.pixelSize: 15
               text: "Foundation checks for updates automatically and installs security fixes in the background. The taskbar tells you when other updates are ready." }
    }
}
