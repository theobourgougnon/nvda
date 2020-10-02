#NVDAObjects/UIA/edge.py
#A part of NonVisual Desktop Access (NVDA)
#This file is covered by the GNU General Public License.
#See the file COPYING for more details.
#Copyright (C) 2015-2017 NV Access Limited, Babbage B.V.

from comtypes import COMError
from comtypes.automation import VARIANT
from ctypes import byref
import winVersion
from logHandler import log
import eventHandler
import config
import controlTypes
import cursorManager
import re
import aria
import textInfos
import UIAHandler
from UIABrowseMode import UIABrowseModeDocument, UIABrowseModeDocumentTextInfo, UIATextRangeQuickNavItem,UIAControlQuicknavIterator
from UIAUtils import *
from . import UIA, web


class EdgeTextInfo(web.UIAWebTextInfo):
	...


class EdgeTextInfo_preGapRemoval(EdgeTextInfo):

	def _hasEmbedded(self):
		"""Is this textInfo positioned on an embedded child?"""
		children=self._rangeObj.getChildren()
		if children.length:
			child=children.getElement(0)
			if not child.getCurrentPropertyValue(UIAHandler.UIA_IsTextPatternAvailablePropertyId):
				childRange=self.obj.UIATextPattern.rangeFromChild(child)
				if childRange:
					childChildren=childRange.getChildren()
				if childChildren.length==1 and UIAHandler.handler.clientObject.compareElements(child,childChildren.getElement(0)):
					return True
		return False

	def move(self,unit,direction,endPoint=None,skipReplacedContent=True):
		# Skip over non-text element starts and ends
		if not endPoint:
			if direction>0 and unit in (textInfos.UNIT_LINE,textInfos.UNIT_PARAGRAPH):
				return self._collapsedMove(unit,direction,skipReplacedContent)
			elif direction>0:
				res=self._collapsedMove(unit,direction,skipReplacedContent)
				if res!=0:
					# Ensure we move past the start of any elements 
					tempInfo=self.copy()
					while super(EdgeTextInfo,tempInfo).move(textInfos.UNIT_CHARACTER,1)!=0:
						tempInfo.setEndPoint(self,"startToStart")
						if tempInfo.text or tempInfo._hasEmbedded():
							break
						tempInfo.collapse(True)
						self._rangeObj=tempInfo._rangeObj.clone()
				return res
			elif direction<0:
				tempInfo=self.copy()
				res=self._collapsedMove(unit,direction,skipReplacedContent)
				if res!=0:
					while True:
						tempInfo.setEndPoint(self,"startToStart")
						if tempInfo.text or tempInfo._hasEmbedded():
							break
						if super(EdgeTextInfo,self).move(textInfos.UNIT_CHARACTER,-1)==0:
							break
				return res
		else:
			tempInfo=self.copy()
			res=tempInfo.move(unit,direction,skipReplacedContent=skipReplacedContent)
			if res!=0:
				self.setEndPoint(tempInfo,"endToEnd" if endPoint=="end" else "startToStart")
			return res

	def expand(self,unit):
		# Ensure expanding to character/word correctly covers embedded controls
		if unit in (textInfos.UNIT_CHARACTER,textInfos.UNIT_WORD):
			tempInfo=self.copy()
			tempInfo.move(textInfos.UNIT_CHARACTER,1,endPoint="end",skipReplacedContent=False)
			if tempInfo._hasEmbedded():
				self.setEndPoint(tempInfo,"endToEnd")
				return
		super(EdgeTextInfo,self).expand(unit)
		return

	def _getTextWithFieldsForUIARange(self,rootElement,textRange,formatConfig,includeRoot=True,recurseChildren=True,alwaysWalkAncestors=True,_rootElementClipped=(True,True)):
		# Edge zooms into its children at the start.
		# Thus you are already in the deepest first child.
		# Therefore get the deepest enclosing element at the start, get its content, Then do the whole thing again on the content from the end of the enclosing element to the end of its parent, and repete!
		# In other words, get the content while slowly zooming out from the start.
		log.debug("_getTextWithFieldsForUIARange (unbalanced)")
		if not recurseChildren:
			log.debug("recurseChildren is False. Falling back to super")
			for field in super(EdgeTextInfo,self)._getTextWithFieldsForUIARange(rootElement,textRange,formatConfig,includeRoot=includeRoot,alwaysWalkAncestors=True,recurseChildren=False,_rootElementClipped=_rootElementClipped):
				yield field
			return
		if log.isEnabledFor(log.DEBUG):
			log.debug("rootElement: %s"%rootElement.currentLocalizedControlType)
			log.debug("full text: %s"%textRange.getText(-1))
			log.debug("includeRoot: %s"%includeRoot)
		startRange=textRange.clone()
		startRange.MoveEndpointByRange(UIAHandler.TextPatternRangeEndpoint_End,startRange,UIAHandler.TextPatternRangeEndpoint_Start)
		enclosingElement=getEnclosingElementWithCacheFromUIATextRange(startRange,self._controlFieldUIACacheRequest)
		if not enclosingElement:
			log.debug("No enclosingElement. Returning")
			return
		enclosingRange=self.obj.getNormalizedUIATextRangeFromElement(enclosingElement)
		if not enclosingRange:
			log.debug("enclosingRange is NULL. Returning")
			return
		if log.isEnabledFor(log.DEBUG):
			log.debug("enclosingElement: %s"%enclosingElement.currentLocalizedControlType)
		startRange.MoveEndpointByRange(UIAHandler.TextPatternRangeEndpoint_End,enclosingRange,UIAHandler.TextPatternRangeEndpoint_End)
		if startRange.CompareEndpoints(UIAHandler.TextPatternRangeEndpoint_End,textRange,UIAHandler.TextPatternRangeEndpoint_End)>0:
			startRange.MoveEndpointByRange(UIAHandler.TextPatternRangeEndpoint_End,textRange,UIAHandler.TextPatternRangeEndpoint_End)
		# Ensure we don't now have a collapsed range
		if startRange.CompareEndpoints(UIAHandler.TextPatternRangeEndpoint_End,startRange,UIAHandler.TextPatternRangeEndpoint_Start)<=0:
			log.debug("Collapsed range. Returning")
			return
		# check for an embedded child
		childElements=getChildrenWithCacheFromUIATextRange(startRange,self._controlFieldUIACacheRequest)
		if childElements.length==1 and UIAHandler.handler.clientObject.compareElements(rootElement,childElements.getElement(0)):
			log.debug("Using single embedded child as enclosingElement")
			for field in super(EdgeTextInfo,self)._getTextWithFieldsForUIARange(rootElement,startRange,formatConfig,_rootElementClipped=_rootElementClipped,includeRoot=includeRoot,alwaysWalkAncestors=False,recurseChildren=False):
				yield field
			return
		parents=[]
		parentElement=enclosingElement
		log.debug("Generating ancestors:")
		hasAncestors=False
		while parentElement:
			if log.isEnabledFor(log.DEBUG):
				log.debug("parentElement: %s"%parentElement.currentLocalizedControlType)
			isRoot=UIAHandler.handler.clientObject.compareElements(parentElement,rootElement)
			log.debug("isRoot: %s"%isRoot)
			if not isRoot:
				hasAncestors=True
			if parentElement is not enclosingElement:
				if includeRoot or not isRoot:
					try:
						obj=UIA(windowHandle=self.obj.windowHandle,UIAElement=parentElement,initialUIACachedPropertyIDs=self._controlFieldUIACachedPropertyIDs)
						field=self._getControlFieldForObject(obj)
					except LookupError:
						log.debug("Failed to fetch controlField data for parentElement. Breaking")
						break
					parents.append((parentElement,field))
				else:
					# This is the root but it was not requested for inclusion
					# However we still need the root element itself for further recursion
					parents.append((parentElement,None))
			if isRoot:
				log.debug("Hit root. Breaking")
				break
			log.debug("Fetching next parentElement")
			parentElement=UIAHandler.handler.baseTreeWalker.getParentElementBuildCache(parentElement,self._controlFieldUIACacheRequest)
		log.debug("Done generating parents")
		log.debug("Yielding parents in reverse order")
		for parentElement,field in reversed(parents):
			if field: yield textInfos.FieldCommand("controlStart",field)
		log.debug("Done yielding parents")
		log.debug("Yielding balanced fields for startRange")
		clippedStart=enclosingRange.CompareEndpoints(UIAHandler.TextPatternRangeEndpoint_Start,startRange,UIAHandler.TextPatternRangeEndpoint_Start)<0
		clippedEnd=enclosingRange.CompareEndpoints(UIAHandler.TextPatternRangeEndpoint_End,startRange,UIAHandler.TextPatternRangeEndpoint_End)>0
		for field in super(EdgeTextInfo,self)._getTextWithFieldsForUIARange(enclosingElement,startRange,formatConfig,_rootElementClipped=(clippedStart,clippedEnd),includeRoot=includeRoot or hasAncestors,alwaysWalkAncestors=False,recurseChildren=True):
			yield field
		tempRange=startRange.clone()
		log.debug("Walking parents to yield controlEnds and recurse unbalanced endRanges")
		for parentElement,field in parents:
			if log.isEnabledFor(log.DEBUG):
				log.debug("parentElement: %s"%parentElement.currentLocalizedControlType)
			tempRange.MoveEndpointByRange(UIAHandler.TextPatternRangeEndpoint_Start,tempRange,UIAHandler.TextPatternRangeEndpoint_End)
			parentRange=self.obj.getNormalizedUIATextRangeFromElement(parentElement)
			if parentRange:
				tempRange.MoveEndpointByRange(UIAHandler.TextPatternRangeEndpoint_End,parentRange,UIAHandler.TextPatternRangeEndpoint_End)
				if tempRange.CompareEndpoints(UIAHandler.TextPatternRangeEndpoint_End,textRange,UIAHandler.TextPatternRangeEndpoint_End)>0:
					tempRange.MoveEndpointByRange(UIAHandler.TextPatternRangeEndpoint_End,textRange,UIAHandler.TextPatternRangeEndpoint_End)
					clippedEnd=True
				else:
					clippedEnd=False
				if field:
					clippedStart=parentRange.CompareEndpoints(UIAHandler.TextPatternRangeEndpoint_Start,textRange,UIAHandler.TextPatternRangeEndpoint_Start)<0
					field['_startOfNode']=not clippedStart
					field['_endOfNode']=not clippedEnd
				if tempRange.CompareEndpoints(UIAHandler.TextPatternRangeEndpoint_End,tempRange,UIAHandler.TextPatternRangeEndpoint_Start)>0:
					log.debug("Recursing endRange")
					for endField in self._getTextWithFieldsForUIARange(parentElement,tempRange,formatConfig,_rootElementClipped=(clippedStart,clippedEnd),includeRoot=False,alwaysWalkAncestors=True,recurseChildren=True):
						yield endField
					log.debug("Done recursing endRange")
				else:
					log.debug("No content after parent")
			if field:
				log.debug("Yielding controlEnd for parent")
				yield textInfos.FieldCommand("controlEnd",field)
		log.debug("Done walking parents to yield controlEnds and recurse unbalanced endRanges")
		log.debug("_getTextWithFieldsForUIARange (unbalanced) end")


class EdgeNode(web.UIAWeb):

	_edgeIsPreGapRemoval=winVersion.winVersion.build<15048

	_TextInfo=EdgeTextInfo_preGapRemoval if _edgeIsPreGapRemoval else EdgeTextInfo

	def getNormalizedUIATextRangeFromElement(self,UIAElement):
		textRange = super().getNormalizedUIATextRangeFromElement(UIAElement)
		if not textRange or not self._edgeIsPreGapRemoval:
			return textRange
		#Move the start of a UIA text range past any element start character stops
		lastCharInfo = EdgeTextInfo_preGapRemoval(self,None, _rangeObj=textRange)
		lastCharInfo._rangeObj = textRange
		charInfo = lastCharInfo.copy()
		charInfo.collapse()
		while super(EdgeTextInfo,charInfo).move(textInfos.UNIT_CHARACTER,1)!=0:
			charInfo.setEndPoint(lastCharInfo,"startToStart")
			if charInfo.text or charInfo._hasEmbedded():
				break
			lastCharInfo.setEndPoint(charInfo,"startToEnd")
			charInfo.collapse(True)
		return textRange

	def _get__isTextEmpty(self):
		# NOTE: we can not check the result of the EdgeTextInfo move implementation to determine if we added
		# any characters to the range, since it seems to return 1 even when the text property has not changed.
		# Also we can not move (repeatedly by one character) since this can overrun the end of the field in edge.
		# So instead, we use self to make a text info (which should have the right range) and then use the UIA
		# specific _rangeObj.getText function to get a subset of the full range of characters.
		ti = self.makeTextInfo(self)
		if ti.isCollapsed:
			# it is collapsed therefore it is empty.
			# exit early so we do not have to do not have to fetch `ti.text` which
			# is potentially costly to performance.
			return True
		numberOfCharacters = 2
		text = ti._rangeObj.getText(numberOfCharacters)
		# Edge can report newline for empty fields:
		if text == "\n":
			return True
		return False


class EdgeList(web.List):
	...


class EdgeHTMLRootContainer(EdgeNode):

	def event_gainFocus(self):
		firstChild=self.firstChild
		if isinstance(firstChild,UIA):
			eventHandler.executeEvent("gainFocus",firstChild)
			return
		return super(EdgeHTMLRootContainer,self).event_gainFocus()


class EdgeHeadingQuickNavItem(UIATextRangeQuickNavItem):

	@property
	def level(self):
		if not hasattr(self,'_level'):
			styleVal=getUIATextAttributeValueFromRange(self.textInfo._rangeObj,UIAHandler.UIA_StyleIdAttributeId)
			self._level=styleVal-(UIAHandler.StyleId_Heading1-1) if UIAHandler.StyleId_Heading1<=styleVal<=UIAHandler.StyleId_Heading6 else None
		return self._level

	def isChild(self,parent):
		return self.level>parent.level


def EdgeHeadingQuicknavIterator(itemType,document,position,direction="next"):
	"""
	A helper for L{EdgeHTMLTreeInterceptor._iterNodesByType} that specifically yields L{EdgeHeadingQuickNavItem} objects found in the given document, starting the search from the given position,  searching in the given direction.
	See L{browseMode._iterNodesByType} for details on these specific arguments.
	"""
	# Edge exposes all headings as UIA elements with a controlType of text, and a level. Thus we can quickly search for these.
	# However, sometimes when ARIA is used, the level on the element may not match the level in the text attributes.
	# Therefore we need to search for all levels 1 through 6, even if a specific level is specified.
	# Though this is still much faster than searching text attributes alone
	# #9078: this must be wrapped inside a list, as Python 3 will treat this as iteration.
	levels=list(range(1,7))
	condition=createUIAMultiPropertyCondition({UIAHandler.UIA_ControlTypePropertyId:UIAHandler.UIA_TextControlTypeId,UIAHandler.UIA_LevelPropertyId:levels})
	levelString=itemType[7:]
	for item in UIAControlQuicknavIterator(itemType,document,position,condition,direction=direction,itemClass=EdgeHeadingQuickNavItem):
		# Verify this is the correct heading level via text attributes 
		if item.level and (not levelString or levelString==str(item.level)): 
			yield item


class EdgeHTMLTreeInterceptor(web.UIAWebTreeInterceptor):

	def _get_documentConstantIdentifier(self):
		return self.rootNVDAObject.parent.name

	def _iterNodesByType(self,nodeType,direction="next",pos=None):
		if nodeType.startswith("heading"):
			return EdgeHeadingQuicknavIterator(nodeType,self,pos,direction=direction)
		else:
			return super(EdgeHTMLTreeInterceptor,self)._iterNodesByType(nodeType,direction=direction,pos=pos)


class EdgeHTMLRoot(EdgeNode):

	treeInterceptorClass=EdgeHTMLTreeInterceptor

	def _get_shouldCreateTreeInterceptor(self):
		return self.role==controlTypes.ROLE_DOCUMENT

	def _get_role(self):
		role=super(EdgeHTMLRoot,self).role
		if role==controlTypes.ROLE_PANE:
			role=controlTypes.ROLE_DOCUMENT
		return role
