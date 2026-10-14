# Image attachments

Attach screenshots, photos, or other supported images.

Applies to: Both

## Supported images

The upload path accepts PNG, JPEG, WebP, and GIF. Up to eight images can be attached to a message. Use the attachment controls and remove unwanted images before sending.


## Size handling

The client rejects images over 20 MB. Non-GIF images over 6 MB are resized with a maximum long edge of 2,560 pixels and converted to JPEG; a resulting image still over 6 MB is rejected. GIFs over 6 MB are rejected rather than resized.


## Ask a precise question

For screenshots, describe the issue and identify the relevant area. Cropping to the relevant content can improve readability and reduce unnecessary detail. Do not assume tiny text survives resizing.


## Temporary Chat

Images remain available in temporary Chat even though ordinary document uploads require a saved conversation. Temporary retention rules still apply to the conversation.


## Attach and describe the image

Select the image attachment control and choose supported files. Review the thumbnails and filenames before sending. Remove an accidental image with its remove control. If several screenshots describe a sequence, name the order and explain what happened between them rather than relying on the model to infer chronology.

A strong troubleshooting prompt includes what you clicked, the expected result, and the visible result. For example: “After selecting Save, this error appears. The form should return to the list.” An image can show symptoms, but it does not expose hidden server logs or establish the underlying cause on its own.


## Preserve readable details

Large still images may be resized and converted to JPEG by the client. This can change fine detail and transparency, so crop around small text or provide a separate close-up when that text matters. Keep enough surrounding context to identify the relevant control or document section.

For source code, long logs, or exact error messages, include selectable text in the prompt or a supported text attachment as well. This avoids relying on recognition of tiny characters in a screenshot. If the image is an animation, the accepted GIF format does not mean you should assume every frame will be analyzed as a complete video.


## Resolve image-specific errors

An image over 20 MB is rejected by the client. A still image over 6 MB is processed for resizing, but can still fail if the result is too large or unreadable. Supply a smaller exported image when that occurs. GIFs above 6 MB require a smaller animation or a still frame instead of the still-image resize path.

The eight-image limit is per message. Reduce the selection or send a focused follow-up rather than attaching many nearly identical views. Temporary Chat permits images, but its session can still expire and the model provider still processes the content. Check that no unintended personal information is visible before sending; the attachment preview is your opportunity to remove it.

