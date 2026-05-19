Attribute VB_Name = "XiaoYi_Animations"
' ============================================================
' 小衣 AI 智能穿搭 Agent — 极客暗黑风路演动画宏
' 在 PowerPoint 中按 Alt+F11 打开 VBA 编辑器，粘贴本代码，按 F5 运行
' ============================================================
Option Explicit

Public Sub AddXiaoYiAnimations()
    Dim sld As Slide
    Dim i As Long, totalSlides As Long
    Dim shp As Shape
    Dim mainTitle As Shape
    Dim foundMainTitle As Boolean

    totalSlides = ActivePresentation.Slides.Count
    If totalSlides < 2 Then
        MsgBox "至少需要 2 张幻灯片。", vbExclamation
        Exit Sub
    End If

    ' ========================================================
    ' 步骤 1：全局 — 所有幻灯片切换设为 平滑/淡出，0.5s
    ' ========================================================
    For i = 1 To totalSlides
        Set sld = ActivePresentation.Slides(i)
        With sld.SlideShowTransition
            .EntryEffect = ppEffectFade           ' 淡出切换
            .Duration = 0.5                        ' 0.5 秒凌厉节奏
            .AdvanceOnClick = msoTrue              ' 点击触发
            .AdvanceOnTime = msoFalse
        End With
    Next i

    ' ========================================================
    ' 步骤 2：封面页 (Slide 1) 专属动画
    ' ========================================================
    Set sld = ActivePresentation.Slides(1)
    foundMainTitle = False

    For Each shp In sld.Shapes
        If shp.HasTextFrame Then
            Dim txt As String
            txt = shp.TextFrame.TextRange.Text

            ' 识别主标题 — 包含"小衣"的最大文本框
            If InStr(1, txt, "小衣", vbTextCompare) > 0 And Len(txt) < 10 Then
                If Not foundMainTitle Then
                    Set mainTitle = shp
                    foundMainTitle = True
                Else
                    ' 如果已找到主标题，当前文本框选字号更大的
                    If shp.TextFrame.TextRange.Font.Size > mainTitle.TextFrame.TextRange.Font.Size Then
                        Set mainTitle = shp
                    End If
                End If
            End If
        End If
    Next shp

    ' 先清除可能残留的动画
    ResetSlideAnimations sld

    If foundMainTitle Then
        ' 主标题：基本缩放 (Zoom)，0.5s，先出现
        Dim effMain As Effect
        Set effMain = sld.TimeLine.MainSequence.AddEffect( _
            Shape:=mainTitle, _
            effectId:=msoAnimEffectZoom, _
            Trigger:=msoAnimTriggerWithPrevious)
        With effMain
            .Timing.Duration = 0.5
            .Timing.TriggerType = msoAnimTriggerWithPrevious
            .Exit = msoFalse
        End With
    End If

    ' 其余元素按字体大小和文本长度判断层级
    For Each shp In sld.Shapes
        If shp.HasTextFrame Then
            txt = shp.TextFrame.TextRange.Text
            Dim fs As Single
            fs = shp.TextFrame.TextRange.Font.Size

            ' 跳过主标题（已处理）
            If foundMainTitle And shp Is mainTitle Then GoTo NextShp1

            ' 副标题：大字号、长文本 → 从下飞入，延迟 0.3s
            If fs >= 18 And Len(txt) > 15 Then
                Dim effSub As Effect
                Set effSub = sld.TimeLine.MainSequence.AddEffect( _
                    Shape:=shp, _
                    effectId:=msoAnimEffectFly, _
                    trigger:=msoAnimTriggerWithPrevious)
                With effSub
                    .EffectParameters.Direction = msoAnimDirectionBottom
                    .Timing.Duration = 0.5
                    .Timing.TriggerDelayTime = 0.3
                End With
            ElseIf fs >= 10 And fs < 18 Then
                ' 中等文本（标签行）→ 淡入，延迟 0.6s
                Dim effMid As Effect
                Set effMid = sld.TimeLine.MainSequence.AddEffect( _
                    Shape:=shp, _
                    effectId:=msoAnimEffectFade, _
                    trigger:=msoAnimTriggerWithPrevious)
                With effMid
                    .Timing.Duration = 0.4
                    .Timing.TriggerDelayTime = 0.6
                End With
            End If
        Else
            ' 非文本形状（装饰）→ 淡入，0.5s 后
            Dim effDeco As Effect
            Set effDeco = sld.TimeLine.MainSequence.AddEffect( _
                Shape:=shp, _
                effectId:=msoAnimEffectFade, _
                trigger:=msoAnimTriggerWithPrevious)
            With effDeco
                .Timing.Duration = 0.4
                .Timing.TriggerDelayTime = 0.5
            End With
        End If
NextShp1:
    Next shp

    ' ========================================================
    ' 步骤 3：内容页 (Slide 2 至 倒数第 2 页) 通用动画
    ' ========================================================
    Dim j As Long
    For i = 2 To totalSlides - 1
        Set sld = ActivePresentation.Slides(i)
        ResetSlideAnimations sld
        AnimateContentSlide sld, i
    Next i

    ' ========================================================
    ' 步骤 4：结尾页 (最后一页) — 全员缩放/淡入聚合
    ' ========================================================
    Set sld = ActivePresentation.Slides(totalSlides)
    ResetSlideAnimations sld

    Dim foundBigTitle As Boolean
    foundBigTitle = False
    For Each shp In sld.Shapes
        If shp.HasTextFrame Then
            txt = shp.TextFrame.TextRange.Text
            fs = shp.TextFrame.TextRange.Font.Size

            ' 大字"谢谢" → Zoom 出场
            If (InStr(1, txt, "谢谢", vbTextCompare) > 0 Or fs >= 60) And Not foundBigTitle Then
                foundBigTitle = True
                Dim effThanks As Effect
                Set effThanks = sld.TimeLine.MainSequence.AddEffect( _
                    Shape:=shp, _
                    effectId:=msoAnimEffectZoom, _
                    trigger:=msoAnimTriggerWithPrevious)
                With effThanks
                    .Timing.Duration = 0.6
                End With
            Else
                ' 其余元素依次淡入，每项延迟 0.12s
                Dim delayOffset As Double
                delayOffset = 0.2 + (0.12 * j)
                Dim effEnd As Effect
                Set effEnd = sld.TimeLine.MainSequence.AddEffect( _
                    Shape:=shp, _
                    effectId:=msoAnimEffectFade, _
                    trigger:=msoAnimTriggerWithPrevious)
                With effEnd
                    .Timing.Duration = 0.4
                    .Timing.TriggerDelayTime = delayOffset
                End With
                j = j + 1
            End If
        Else
            Dim effEndDeco As Effect
            Set effEndDeco = sld.TimeLine.MainSequence.AddEffect( _
                Shape:=shp, _
                effectId:=msoAnimEffectFade, _
                trigger:=msoAnimTriggerWithPrevious)
            With effEndDeco
                .Timing.Duration = 0.4
                .Timing.TriggerDelayTime = 0.3 + (0.12 * j)
            End With
            j = j + 1
        End If
    Next shp

    MsgBox "小衣 PPT 极客动画全部添加完成！" & vbCrLf & vbCrLf & _
           "共处理 " & totalSlides & " 页幻灯片。" & vbCrLf & _
           "请按 Shift+F5 从当前页预览，或 F5 从头播放。", vbInformation, "Done"

End Sub


' ============================================================
' 辅助函数：清除单页幻灯片所有动画
' ============================================================
Private Sub ResetSlideAnimations(sld As Slide)
    Dim seq As Sequence
    Set seq = sld.TimeLine.MainSequence
    Dim k As Long
    For k = seq.Count To 1 Step -1
        seq.Item(k).Delete
    Next k
End Sub


' ============================================================
' 辅助函数：为内容页添加通用动画
' ============================================================
Private Sub AnimateContentSlide(sld As Slide, ByVal slideIndex As Long)
    Dim shp As Shape
    Dim txt As String, fs As Single
    Dim hasTitle As Boolean
    Dim titleShp As Shape
    Dim bodyShapes As New Collection
    Dim decoShapes As New Collection
    Dim i As Long
    Dim eff As Effect
    Dim maxFont As Single

    ' ---- 第一遍：找出标题（字号最大的文本形状） ----
    maxFont = 0
    For Each shp In sld.Shapes
        If shp.HasTextFrame Then
            On Error Resume Next
            fs = shp.TextFrame.TextRange.Font.Size
            On Error GoTo 0
            If fs > maxFont Then
                maxFont = fs
                Set titleShp = shp
            End If
        End If
    Next shp

    hasTitle = (maxFont > 18)

    ' ---- 第二遍：分类 ----
    For Each shp In sld.Shapes
        If shp.HasTextFrame Then
            On Error Resume Next
            fs = shp.TextFrame.TextRange.Font.Size
            txt = shp.TextFrame.TextRange.Text
            On Error GoTo 0

            If hasTitle And shp Is titleShp Then
                ' 这是标题，单独处理
            ElseIf fs >= 10 And Len(txt) > 10 Then
                bodyShapes.Add shp
            Else
                decoShapes.Add shp
            End If
        Else
            decoShapes.Add shp
        End If
    Next shp

    ' ---- 添加动画 ----
    Dim seq As Sequence
    Set seq = sld.TimeLine.MainSequence

    ' 1) 标题：从左侧飞入，0.3s
    If hasTitle Then
        Set eff = seq.AddEffect(Shape:=titleShp, _
            effectId:=msoAnimEffectFly, _
            trigger:=msoAnimTriggerWithPrevious)
        With eff
            .EffectParameters.Direction = msoAnimDirectionLeft
            .Timing.Duration = 0.3
        End With
    End If

    ' 2) 正文/卡片形状：向上擦除 (Wipe)，每个延迟 0.15s
    Dim delay As Double
    delay = 0.15
    For i = 1 To bodyShapes.Count
        Set shp = bodyShapes.Item(i)
        Set eff = seq.AddEffect(Shape:=shp, _
            effectId:=msoAnimEffectWipe, _
            trigger:=msoAnimTriggerWithPrevious)
        With eff
            .EffectParameters.Direction = msoAnimDirectionBottom
            .Timing.Duration = 0.35
            .Timing.TriggerDelayTime = delay
        End With
        delay = delay + 0.15
    Next i

    ' 3) 装饰元素：淡入，最后一起出现
    For i = 1 To decoShapes.Count
        Set shp = decoShapes.Item(i)
        Set eff = seq.AddEffect(Shape:=shp, _
            effectId:=msoAnimEffectFade, _
            trigger:=msoAnimTriggerWithPrevious)
        With eff
            .Timing.Duration = 0.3
            .Timing.TriggerDelayTime = delay
        End With
    Next i

End Sub
